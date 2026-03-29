import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  Loader2,
  AlertCircle,
  DollarSign,
  Layers,
  ShieldAlert,
  ClipboardList,
  Wallet,
  XCircle,
  AlertTriangle,
} from 'lucide-react';
import GlassCard from '../components/ui/GlassCard';
import MetricCard from '../components/ui/MetricCard';
import { cn } from '../lib/utils';
import { usePaperTrading } from '../hooks/usePaperTrading';
import type { PlaceOrderRequest } from '../types';

const EMPTY_FORM: PlaceOrderRequest = {
  ticker: '',
  direction: 'BUY',
  qty: 1,
  price: 0,
  stop_loss: undefined,
  target: undefined,
};

export default function PaperTradingPage() {
  const { status, loading, error, placeOrder, cancelOrder, closeAll } = usePaperTrading();
  const [form, setForm] = useState<PlaceOrderRequest>({ ...EMPTY_FORM });
  const [submitting, setSubmitting] = useState(false);
  const [orderMsg, setOrderMsg] = useState<{ text: string; ok: boolean } | null>(null);
  const [confirmCloseAll, setConfirmCloseAll] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.ticker || form.price <= 0 || form.qty <= 0) return;
    setSubmitting(true);
    setOrderMsg(null);
    try {
      const result = await placeOrder({
        ...form,
        stop_loss: form.stop_loss || undefined,
        target: form.target || undefined,
      });
      setOrderMsg({ text: `${result.order_id} placed`, ok: result.success });
      if (result.success) setForm({ ...EMPTY_FORM });
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Order failed';
      setOrderMsg({ text: msg, ok: false });
    } finally {
      setSubmitting(false);
    }
  };

  const handleCloseAll = async () => {
    setConfirmCloseAll(false);
    try {
      await closeAll();
      setOrderMsg({ text: 'All positions closed', ok: true });
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Close all failed';
      setOrderMsg({ text: msg, ok: false });
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <Loader2 size={48} className="text-trading-ai animate-spin mb-4" />
        <p className="text-slate-400 text-sm">Loading paper trading status...</p>
      </div>
    );
  }

  if (error || !status) {
    return (
      <div className="flex flex-col items-center justify-center py-24">
        <AlertCircle size={48} className="text-trading-alert mb-4" />
        <p className="text-slate-400 text-sm">Failed to load status: {error}</p>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
      className="space-y-6"
    >
      {/* Paper Mode Banner */}
      {status.paper_mode && (
        <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-trading-ai/10 border border-trading-ai/20 text-trading-ai text-sm">
          <ShieldAlert size={16} />
          Paper Mode Active — no real orders are sent
        </div>
      )}

      {/* Kill Switch Alert */}
      {status.kill_switch_active && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-red-500/15 border border-red-500/30 text-red-400 text-sm font-medium">
          <AlertTriangle size={18} />
          Kill Switch Triggered — {status.kill_switch_reason || 'Daily loss limit reached'}
        </div>
      )}

      {/* Status Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          title="Capital"
          value={`₹${(status.capital || 0).toLocaleString('en-IN')}`}
          icon={Wallet}
          color="info"
        />
        <MetricCard
          title="Open Positions"
          value={`${status.open_positions} / ${status.max_positions}`}
          icon={Layers}
          color="ai"
        />
        <MetricCard
          title="Daily P&L"
          value={`${status.daily_pnl >= 0 ? '+' : ''}${status.daily_pnl.toFixed(2)}%`}
          change={status.daily_pnl}
          icon={DollarSign}
          color={status.daily_pnl >= 0 ? 'bull' : 'bear'}
        />
        <MetricCard
          title="Orders Today"
          value={status.orders_today}
          icon={ClipboardList}
          color="info"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Order Form */}
        <GlassCard className="lg:col-span-1">
          <h3 className="text-sm font-semibold text-white mb-4">Place Order</h3>
          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label className="text-xs text-slate-500 mb-1 block">Ticker</label>
              <input
                type="text"
                value={form.ticker}
                onChange={(e) => setForm({ ...form, ticker: e.target.value.toUpperCase() })}
                placeholder="NSE:RELIANCE"
                className="w-full bg-slate-800/60 border border-trading-border rounded-lg px-3 py-2 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-trading-ai"
              />
            </div>

            <div>
              <label className="text-xs text-slate-500 mb-1 block">Direction</label>
              <div className="flex gap-2">
                {(['BUY', 'SELL'] as const).map((dir) => (
                  <button
                    key={dir}
                    type="button"
                    onClick={() => setForm({ ...form, direction: dir })}
                    className={cn(
                      'flex-1 py-2 rounded-lg text-sm font-bold transition-all',
                      form.direction === dir
                        ? dir === 'BUY'
                          ? 'bg-trading-bull/20 text-trading-bull border border-trading-bull/30'
                          : 'bg-trading-bear/20 text-trading-bear border border-trading-bear/30'
                        : 'bg-slate-800/40 text-slate-500 border border-trading-border hover:text-slate-300'
                    )}
                  >
                    {dir}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-slate-500 mb-1 block">Qty</label>
                <input
                  type="number"
                  min={1}
                  value={form.qty}
                  onChange={(e) => setForm({ ...form, qty: Number(e.target.value) })}
                  className="w-full bg-slate-800/60 border border-trading-border rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-trading-ai"
                />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">Price</label>
                <input
                  type="number"
                  step="0.05"
                  min={0}
                  value={form.price || ''}
                  onChange={(e) => setForm({ ...form, price: Number(e.target.value) })}
                  className="w-full bg-slate-800/60 border border-trading-border rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-trading-ai"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-slate-500 mb-1 block">Stop Loss</label>
                <input
                  type="number"
                  step="0.05"
                  min={0}
                  value={form.stop_loss || ''}
                  onChange={(e) => setForm({ ...form, stop_loss: Number(e.target.value) || undefined })}
                  className="w-full bg-slate-800/60 border border-trading-border rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-trading-ai"
                />
              </div>
              <div>
                <label className="text-xs text-slate-500 mb-1 block">Target</label>
                <input
                  type="number"
                  step="0.05"
                  min={0}
                  value={form.target || ''}
                  onChange={(e) => setForm({ ...form, target: Number(e.target.value) || undefined })}
                  className="w-full bg-slate-800/60 border border-trading-border rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-trading-ai"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={submitting || !form.ticker || form.price <= 0 || status.kill_switch_active}
              className={cn(
                'w-full py-2.5 rounded-lg text-sm font-bold transition-all',
                status.kill_switch_active
                  ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                  : form.direction === 'BUY'
                    ? 'bg-trading-bull/20 text-trading-bull hover:bg-trading-bull/30 border border-trading-bull/30'
                    : 'bg-trading-bear/20 text-trading-bear hover:bg-trading-bear/30 border border-trading-bear/30'
              )}
            >
              {submitting ? 'Placing...' : `Place ${form.direction} Order`}
            </button>

            {orderMsg && (
              <div className={cn(
                'text-xs px-3 py-2 rounded-lg',
                orderMsg.ok ? 'bg-trading-bull/10 text-trading-bull' : 'bg-trading-bear/10 text-trading-bear'
              )}>
                {orderMsg.text}
              </div>
            )}
          </form>
        </GlassCard>

        {/* Positions Table */}
        <GlassCard className="lg:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-white">Open Positions</h3>
            {status.positions.length > 0 && (
              confirmCloseAll ? (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-red-400">Close all?</span>
                  <button
                    onClick={handleCloseAll}
                    className="px-3 py-1 rounded text-xs font-bold bg-red-500/20 text-red-400 border border-red-500/30 hover:bg-red-500/30"
                  >
                    Confirm
                  </button>
                  <button
                    onClick={() => setConfirmCloseAll(false)}
                    className="px-3 py-1 rounded text-xs text-slate-400 hover:text-white"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setConfirmCloseAll(true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 transition-colors"
                >
                  <AlertTriangle size={12} />
                  Close All
                </button>
              )
            )}
          </div>

          {status.positions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12">
              <Layers size={40} className="text-slate-600 mb-3" />
              <p className="text-slate-500 text-sm">No open positions</p>
              <p className="text-slate-600 text-xs mt-1">Place an order to get started</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-slate-500 uppercase tracking-wider border-b border-trading-border">
                    <th className="text-left py-3 px-2">Order ID</th>
                    <th className="text-left py-3 px-2">Ticker</th>
                    <th className="text-center py-3 px-2">Dir</th>
                    <th className="text-right py-3 px-2 font-mono">Qty</th>
                    <th className="text-right py-3 px-2 font-mono">Entry</th>
                    <th className="text-right py-3 px-2 font-mono hidden md:table-cell">SL</th>
                    <th className="text-center py-3 px-2 hidden lg:table-cell">Trail</th>
                    <th className="text-center py-3 px-2 hidden lg:table-cell">Exits</th>
                    <th className="text-center py-3 px-2">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-trading-border/50">
                  {status.positions.map((pos, idx) => (
                    <motion.tr
                      key={pos.order_id}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.2, delay: idx * 0.05 }}
                      className="hover:bg-slate-800/30 transition-colors"
                    >
                      <td className="py-3 px-2">
                        <span className="font-mono text-xs text-slate-400">{pos.order_id}</span>
                      </td>
                      <td className="py-3 px-2">
                        <span className="font-mono font-bold text-white">{pos.ticker}</span>
                      </td>
                      <td className="py-3 px-2 text-center">
                        <span className={cn(
                          'text-xs font-bold',
                          pos.direction === 'BUY' ? 'text-trading-bull' : 'text-trading-bear'
                        )}>
                          {pos.direction}
                        </span>
                      </td>
                      <td className="py-3 px-2 text-right font-mono text-slate-300">{pos.qty}</td>
                      <td className="py-3 px-2 text-right font-mono text-slate-300">
                        {pos.entry_price.toFixed(2)}
                      </td>
                      <td className="py-3 px-2 text-right font-mono text-trading-bear hidden md:table-cell">
                        {pos.stop_loss.toFixed(2)}
                      </td>
                      <td className="py-3 px-2 text-center hidden lg:table-cell">
                        {pos.trail_active ? (
                          <span className="text-xs text-trading-bull">ON</span>
                        ) : (
                          <span className="text-xs text-slate-600">OFF</span>
                        )}
                      </td>
                      <td className="py-3 px-2 text-center font-mono text-slate-400 hidden lg:table-cell">
                        {pos.partial_exits}
                      </td>
                      <td className="py-3 px-2 text-center">
                        <button
                          onClick={() => cancelOrder(pos.order_id)}
                          className="p-1.5 rounded-md text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                          title="Cancel order"
                        >
                          <XCircle size={16} />
                        </button>
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </GlassCard>
      </div>
    </motion.div>
  );
}
