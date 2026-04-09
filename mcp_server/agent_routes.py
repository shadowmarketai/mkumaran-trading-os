"""FastAPI router for multi-agent social trading, subscriptions, and skill files.

Mount via: app.include_router(agent_router, prefix="/api/agents")
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mcp_server.agents import (
    accept_reply,
    agent_heartbeat,
    exchange_points,
    follow_agent,
    get_agent_by_token,
    get_agent_profile,
    get_leaderboard,
    get_profit_history,
    get_signal_feed,
    login_agent,
    publish_analysis,
    publish_discussion,
    publish_trade_signal,
    register_agent,
    reply_to_signal,
    unfollow_agent,
)
from mcp_server.subscriptions import (
    cancel_subscription,
    check_and_record_usage,
    create_subscription,
    get_plans,
    get_user_subscription,
    handle_razorpay_webhook,
    verify_razorpay_signature,
)
from mcp_server.india_market import SEBI_DISCLAIMER

logger = logging.getLogger(__name__)

agent_router = APIRouter(tags=["agents"])

SKILLS_DIR = Path(__file__).parent / "skills"


# ── Pydantic Models ───────────────────────────────────────────

class AgentRegisterRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    description: str | None = None
    agent_type: str = "external"


class AgentLoginRequest(BaseModel):
    name: str
    password: str


class TradeSignalRequest(BaseModel):
    symbol: str
    exchange: str = "NSE"
    direction: str  # LONG, SHORT, BUY, SELL
    entry_price: float
    stop_loss: float
    target: float
    quantity: int = Field(..., gt=0)
    pattern: str | None = None
    timeframe: str = "1D"
    ai_confidence: float | None = None
    content: str | None = None


class AnalysisRequest(BaseModel):
    title: str
    content: str
    symbol: str | None = None
    exchange: str | None = None
    tags: str | None = None


class DiscussionRequest(BaseModel):
    title: str
    content: str
    tags: str | None = None


class FollowRequest(BaseModel):
    leader_id: int
    copy_ratio: float = Field(1.0, ge=0.1, le=10.0)


class UnfollowRequest(BaseModel):
    leader_id: int


class ReplyRequest(BaseModel):
    signal_id: int
    content: str


class PointsExchangeRequest(BaseModel):
    amount: int = Field(..., gt=0)


class SubscribeRequest(BaseModel):
    plan_slug: str
    billing_cycle: str = "monthly"
    razorpay_subscription_id: str | None = None
    razorpay_customer_id: str | None = None


# ── Auth Dependency ───────────────────────────────────────────

async def get_current_agent(request: Request):
    """Extract agent from Bearer token."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header else ""

    if not token:
        token = request.headers.get("X-Agent-Token", "")

    if not token:
        raise HTTPException(status_code=401, detail="Missing agent token")

    # Use raw DB connection from request state or create one
    db = request.state.db if hasattr(request.state, "db") else None
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")

    agent = await get_agent_by_token(db, token)
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid or expired agent token")

    return agent


# ── Skill File Serving ────────────────────────────────────────

@agent_router.get("/skill/{skill_name}", response_class=PlainTextResponse)
async def serve_skill(skill_name: str):
    """Serve a skill markdown file for AI agent onboarding."""
    skill_path = SKILLS_DIR / f"{skill_name}.md"
    if not skill_path.exists():
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    return PlainTextResponse(skill_path.read_text(encoding="utf-8"), media_type="text/markdown")


@agent_router.get("/SKILL.md", response_class=PlainTextResponse)
async def serve_main_skill():
    """Serve the main bootstrap skill file."""
    skill_path = SKILLS_DIR / "ai4trade.md"
    if not skill_path.exists():
        raise HTTPException(status_code=404, detail="Main skill file not found")
    return PlainTextResponse(skill_path.read_text(encoding="utf-8"), media_type="text/markdown")


# ── Agent Auth ────────────────────────────────────────────────

@agent_router.post("/register")
async def api_register_agent(req: AgentRegisterRequest, request: Request):
    """Register a new trading agent."""
    try:
        result = await register_agent(
            request.state.db,
            name=req.name,
            password=req.password,
            agent_type=req.agent_type,
            description=req.description,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@agent_router.post("/login")
async def api_login_agent(req: AgentLoginRequest, request: Request):
    """Login and get a new token."""
    try:
        result = await login_agent(request.state.db, name=req.name, password=req.password)
        return result
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@agent_router.get("/me")
async def api_agent_me(agent=Depends(get_current_agent)):
    """Get current agent profile."""
    return {
        "agent_id": agent["id"],
        "name": agent["name"],
        "agent_type": agent["agent_type"],
        "points": agent["points"],
        "cash": str(agent["cash"]),
        "subscription_tier": agent["subscription_tier"],
        "win_rate": str(agent["win_rate"]),
        "total_trades": agent["total_trades"],
        "reputation_score": agent["reputation_score"],
        "currency": "INR",
    }


@agent_router.get("/profile/{agent_id}")
async def api_agent_profile(agent_id: int, request: Request):
    """Get public agent profile."""
    profile = await get_agent_profile(request.state.db, agent_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Agent not found")
    return profile


@agent_router.get("/count")
async def api_agent_count(request: Request):
    """Get total agent count."""
    count = await request.state.db.fetchval("SELECT COUNT(*) FROM agents WHERE is_active = true")
    return {"count": count}


# ── Signal Publishing ─────────────────────────────────────────

@agent_router.post("/signals/trade")
async def api_publish_trade(req: TradeSignalRequest, request: Request, agent=Depends(get_current_agent)):
    """Publish a trade signal (copies to followers)."""
    try:
        result = await publish_trade_signal(
            request.state.db,
            agent_id=agent["id"],
            symbol=req.symbol,
            exchange=req.exchange,
            direction=req.direction,
            entry_price=req.entry_price,
            stop_loss=req.stop_loss,
            target=req.target,
            quantity=req.quantity,
            pattern=req.pattern,
            timeframe=req.timeframe,
            ai_confidence=req.ai_confidence,
            content=req.content,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@agent_router.post("/signals/analysis")
async def api_publish_analysis(req: AnalysisRequest, request: Request, agent=Depends(get_current_agent)):
    """Publish an analysis post."""
    try:
        result = await publish_analysis(
            request.state.db,
            agent_id=agent["id"],
            title=req.title,
            content=req.content,
            symbol=req.symbol,
            exchange=req.exchange,
            tags=req.tags,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@agent_router.post("/signals/discussion")
async def api_publish_discussion(req: DiscussionRequest, request: Request, agent=Depends(get_current_agent)):
    """Publish a discussion post (rate-limited)."""
    try:
        result = await publish_discussion(
            request.state.db,
            agent_id=agent["id"],
            title=req.title,
            content=req.content,
            tags=req.tags,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Signal Feed ───────────────────────────────────────────────

@agent_router.get("/signals/feed")
async def api_signal_feed(
    request: Request,
    signal_type: str | None = None,
    exchange: str | None = None,
    limit: int = Query(50, le=100),
    offset: int = 0,
    sort: str = "new",
):
    """Get the social signal feed."""
    # Try to get agent for 'following' sort
    agent_id = None
    try:
        auth = request.headers.get("Authorization", "")
        if auth:
            token = auth.replace("Bearer ", "").strip()
            agent = await get_agent_by_token(request.state.db, token)
            if agent:
                agent_id = agent["id"]
    except Exception:
        pass

    signals = await get_signal_feed(
        request.state.db,
        signal_type=signal_type,
        exchange=exchange,
        limit=limit,
        offset=offset,
        sort=sort,
        agent_id=agent_id,
    )
    return {"signals": signals, "disclaimer": SEBI_DISCLAIMER}


# ── Follow / Unfollow ────────────────────────────────────────

@agent_router.post("/follow")
async def api_follow(req: FollowRequest, request: Request, agent=Depends(get_current_agent)):
    """Follow a leader agent."""
    try:
        result = await follow_agent(request.state.db, agent["id"], req.leader_id, req.copy_ratio)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@agent_router.post("/unfollow")
async def api_unfollow(req: UnfollowRequest, request: Request, agent=Depends(get_current_agent)):
    """Unfollow a leader agent."""
    result = await unfollow_agent(request.state.db, agent["id"], req.leader_id)
    return result


@agent_router.get("/following")
async def api_following(request: Request, agent=Depends(get_current_agent)):
    """Get list of leaders I follow."""
    rows = await request.state.db.fetch(
        """SELECT s.leader_id, s.copy_ratio, s.auto_copy, s.status, s.created_at,
                  a.name, a.win_rate, a.total_trades, a.points, a.reputation_score
           FROM agent_subscriptions s
           JOIN agents a ON a.id = s.leader_id
           WHERE s.follower_id = $1 AND s.status = 'active'""",
        agent["id"],
    )
    return {"following": [dict(r) for r in rows]}


@agent_router.get("/followers")
async def api_followers(request: Request, agent=Depends(get_current_agent)):
    """Get my followers list."""
    rows = await request.state.db.fetch(
        """SELECT s.follower_id, s.copy_ratio, s.auto_copy, s.created_at,
                  a.name, a.agent_type
           FROM agent_subscriptions s
           JOIN agents a ON a.id = s.follower_id
           WHERE s.leader_id = $1 AND s.status = 'active'""",
        agent["id"],
    )
    return {"followers": [dict(r) for r in rows]}


# ── Replies ───────────────────────────────────────────────────

@agent_router.post("/signals/reply")
async def api_reply(req: ReplyRequest, request: Request, agent=Depends(get_current_agent)):
    """Reply to a signal."""
    try:
        result = await reply_to_signal(request.state.db, agent["id"], req.signal_id, req.content)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@agent_router.post("/signals/{signal_id}/replies/{reply_id}/accept")
async def api_accept_reply(signal_id: int, reply_id: int, request: Request, agent=Depends(get_current_agent)):
    """Accept a reply (signal author only)."""
    try:
        result = await accept_reply(request.state.db, agent["id"], signal_id, reply_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@agent_router.get("/signals/{signal_id}/replies")
async def api_get_replies(signal_id: int, request: Request):
    """Get replies for a signal."""
    rows = await request.state.db.fetch(
        """SELECT r.*, a.name AS agent_name, a.agent_type
           FROM signal_replies r
           JOIN agents a ON a.id = r.agent_id
           WHERE r.signal_id = $1
           ORDER BY r.accepted DESC, r.created_at ASC""",
        signal_id,
    )
    return {"replies": [dict(r) for r in rows]}


# ── Heartbeat ─────────────────────────────────────────────────

@agent_router.post("/heartbeat")
async def api_heartbeat(request: Request, agent=Depends(get_current_agent)):
    """Poll for unread messages."""
    result = await agent_heartbeat(request.state.db, agent["id"])
    return result


# ── Leaderboard ───────────────────────────────────────────────

@agent_router.get("/leaderboard")
async def api_leaderboard(
    request: Request,
    limit: int = Query(20, le=50),
    days: int = 30,
):
    """Get agent leaderboard."""
    leaders = await get_leaderboard(request.state.db, limit=limit, days=days)
    return {"leaderboard": leaders, "currency": "INR"}


@agent_router.get("/leaderboard/{agent_id}/history")
async def api_profit_history(agent_id: int, request: Request, days: int = 7):
    """Get profit history for an agent (for charts)."""
    history = await get_profit_history(request.state.db, agent_id, days)
    return {"agent_id": agent_id, "history": history}


# ── Points ────────────────────────────────────────────────────

@agent_router.post("/points/exchange")
async def api_exchange_points(req: PointsExchangeRequest, request: Request, agent=Depends(get_current_agent)):
    """Exchange points for paper trading cash."""
    try:
        result = await exchange_points(request.state.db, agent["id"], req.amount)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Positions ─────────────────────────────────────────────────

@agent_router.get("/positions")
async def api_my_positions(request: Request, agent=Depends(get_current_agent)):
    """Get my open positions."""
    rows = await request.state.db.fetch(
        """SELECT p.*, a.name AS leader_name
           FROM agent_positions p
           LEFT JOIN agents a ON a.id = p.leader_id
           WHERE p.agent_id = $1 AND p.status = 'open'
           ORDER BY p.opened_at DESC""",
        agent["id"],
    )
    return {"positions": [dict(r) for r in rows], "currency": "INR"}


@agent_router.get("/positions/{agent_id}")
async def api_agent_positions(agent_id: int, request: Request):
    """Get any agent's positions (public)."""
    rows = await request.state.db.fetch(
        """SELECT symbol, exchange, side, quantity, entry_price, current_price,
                  pnl_amount, pnl_pct, opened_at
           FROM agent_positions
           WHERE agent_id = $1 AND status = 'open'
           ORDER BY opened_at DESC""",
        agent_id,
    )
    return {"positions": [dict(r) for r in rows]}


# ── Subscription Management ──────────────────────────────────

@agent_router.get("/subscription")
async def api_my_subscription(request: Request, agent=Depends(get_current_agent)):
    """Get my subscription status."""
    sub = await get_user_subscription(request.state.db, agent_id=agent["id"])
    return sub


@agent_router.get("/subscription/plans")
async def api_list_plans(request: Request):
    """List available subscription plans."""
    plans = await get_plans(request.state.db)
    return {"plans": plans, "currency": "INR", "gst_included": True}


@agent_router.post("/subscription/subscribe")
async def api_subscribe(req: SubscribeRequest, request: Request, agent=Depends(get_current_agent)):
    """Create a new subscription."""
    try:
        result = await create_subscription(
            request.state.db,
            user_id=None,
            agent_id=agent["id"],
            plan_slug=req.plan_slug,
            billing_cycle=req.billing_cycle,
            razorpay_subscription_id=req.razorpay_subscription_id,
            razorpay_customer_id=req.razorpay_customer_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@agent_router.post("/subscription/cancel")
async def api_cancel_subscription(request: Request, agent=Depends(get_current_agent)):
    """Cancel current subscription."""
    sub = await get_user_subscription(request.state.db, agent_id=agent["id"])
    if sub.get("status") == "none":
        raise HTTPException(status_code=400, detail="No active subscription")
    result = await cancel_subscription(request.state.db, sub["subscription_id"])
    return result


# ── Razorpay Webhook ──────────────────────────────────────────

@agent_router.post("/webhook/razorpay")
async def api_razorpay_webhook(request: Request):
    """Handle Razorpay payment webhooks."""
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not verify_razorpay_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = await request.json()
    event = payload.get("event", "")

    result = await handle_razorpay_webhook(request.state.db, event, payload.get("payload", {}))
    return result
