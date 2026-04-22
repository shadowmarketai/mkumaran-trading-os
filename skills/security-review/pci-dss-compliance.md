| name | description |
|------|-------------|
| pci-dss-compliance | Use this skill when integrating payment processing, handling card data, implementing Stripe/Razorpay, or configuring webhook security. Ensures PCI DSS compliance and secure payment flows. |

# PCI DSS Compliance Skill

This skill ensures all payment processing follows PCI DSS (Payment Card Industry Data Security Standard) requirements, with focus on scope reduction through tokenization.

## When to Activate

- Integrating Stripe, Razorpay, or other payment processors
- Handling any payment card data (even indirectly)
- Implementing subscription billing or recurring payments
- Building checkout flows
- Configuring payment webhooks
- Implementing refund or chargeback handling
- Storing any payment-related data

## PCI DSS Compliance Checklist

### 1. Scope Reduction — Never Touch Card Data

#### Tokenization with Stripe

```typescript
// PASS: CORRECT — Client-side tokenization (card data never hits your server)
// Frontend: Use Stripe Elements
import { loadStripe } from '@stripe/stripe-js';
import { Elements, CardElement, useStripe } from '@stripe/react-stripe-js';

const stripePromise = loadStripe(process.env.NEXT_PUBLIC_STRIPE_KEY!);

function CheckoutForm() {
  const stripe = useStripe();
  const elements = useElements();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const { paymentMethod, error } = await stripe!.createPaymentMethod({
      type: 'card',
      card: elements!.getElement(CardElement)!,
    });

    if (paymentMethod) {
      // Send only the token to your server — never card numbers
      await fetch('/api/payments', {
        method: 'POST',
        body: JSON.stringify({ paymentMethodId: paymentMethod.id }),
      });
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <CardElement />
      <button type="submit">Pay</button>
    </form>
  );
}

// FAIL: WRONG — Card data sent to your server
app.post('/api/payments', (req, res) => {
  const { cardNumber, cvv, expiry } = req.body; // NEVER DO THIS
});
```

```python
# PASS: CORRECT — Server-side payment intent (no card data)
import stripe
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

async def create_payment_intent(amount: int, currency: str, customer_id: str):
    return stripe.PaymentIntent.create(
        amount=amount,
        currency=currency,
        customer=customer_id,
        payment_method_types=["card"],
        # Stripe handles all card data — your server never sees it
    )

# FAIL: WRONG — Logging card data
logger.info(f"Payment with card {card_number}")  # PCI violation
```

#### Verification Steps

- [ ] Card data NEVER touches your servers (client-side tokenization)
- [ ] Stripe Elements or Checkout used (not custom card fields)
- [ ] No card numbers, CVVs, or full expiry dates in logs
- [ ] No card data in database tables
- [ ] No card data in error messages or stack traces

### 2. Webhook Security

#### Stripe Webhook Verification

```typescript
// PASS: CORRECT — Verify webhook signatures
import Stripe from 'stripe';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);

export async function POST(request: Request) {
  const body = await request.text();
  const signature = request.headers.get('stripe-signature')!;

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(
      body,
      signature,
      process.env.STRIPE_WEBHOOK_SECRET!,
    );
  } catch (err) {
    console.error('Webhook signature verification failed');
    return new Response('Invalid signature', { status: 400 });
  }

  // Process verified event
  switch (event.type) {
    case 'payment_intent.succeeded':
      await handlePaymentSuccess(event.data.object);
      break;
    case 'payment_intent.payment_failed':
      await handlePaymentFailure(event.data.object);
      break;
  }

  return new Response('OK', { status: 200 });
}

// FAIL: WRONG — No signature verification
export async function POST(request: Request) {
  const event = await request.json(); // Trusting unverified payload
  await handlePayment(event);
}
```

```python
# PASS: CORRECT — FastAPI webhook verification
from fastapi import Request, HTTPException
import stripe

@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.environ["STRIPE_WEBHOOK_SECRET"]
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "payment_intent.succeeded":
        await handle_payment_success(event["data"]["object"])

    return {"status": "ok"}
```

#### Verification Steps

- [ ] All webhook endpoints verify signatures
- [ ] Webhook secrets stored in environment variables
- [ ] Webhook endpoints use HTTPS only
- [ ] Idempotency keys used to prevent duplicate processing
- [ ] Failed webhooks have retry handling
- [ ] Webhook events logged for audit trail

### 3. Secure Payment Data Storage

#### What You CAN Store

```typescript
// PASS: CORRECT — Store only tokens and metadata
interface PaymentRecord {
  id: string;
  stripePaymentIntentId: string;  // Token — safe to store
  stripeCustomerId: string;        // Token — safe to store
  amount: number;
  currency: string;
  status: 'pending' | 'succeeded' | 'failed';
  last4: string;                   // Last 4 digits — safe to store
  brand: string;                   // 'visa', 'mastercard' — safe to store
  createdAt: Date;
}

// FAIL: WRONG — Storing sensitive card data
interface BadPaymentRecord {
  cardNumber: string;     // NEVER store
  cvv: string;            // NEVER store
  fullExpiry: string;     // NEVER store (storing month/year separately is OK)
  cardholderName: string; // Avoid storing unless necessary
}
```

#### Verification Steps

- [ ] Only tokens (payment intent IDs, customer IDs) stored
- [ ] Last 4 digits only for display purposes
- [ ] No CVV/CVC stored anywhere, ever
- [ ] No full card numbers in any database table
- [ ] Payment records have proper access controls

### 4. Subscription & Recurring Payments

#### Secure Subscription Management

```typescript
// PASS: CORRECT — Let Stripe manage recurring billing
async function createSubscription(
  customerId: string,
  priceId: string,
): Promise<Stripe.Subscription> {
  const subscription = await stripe.subscriptions.create({
    customer: customerId,
    items: [{ price: priceId }],
    payment_behavior: 'default_incomplete',
    expand: ['latest_invoice.payment_intent'],
  });

  return subscription;
}

// Handle subscription lifecycle via webhooks
async function handleSubscriptionUpdated(sub: Stripe.Subscription) {
  await db.subscriptions.upsert({
    where: { stripeSubscriptionId: sub.id },
    update: {
      status: sub.status,
      currentPeriodEnd: new Date(sub.current_period_end * 1000),
    },
    create: {
      stripeSubscriptionId: sub.id,
      userId: sub.metadata.userId,
      status: sub.status,
      currentPeriodEnd: new Date(sub.current_period_end * 1000),
    },
  });
}
```

#### Verification Steps

- [ ] Billing handled by payment processor (not custom logic)
- [ ] Subscription status synced via webhooks
- [ ] Failed payment retry logic handled by processor
- [ ] Cancellation and proration handled correctly
- [ ] Subscription changes create audit trail

### 5. PCI DSS Network Requirements

#### Segmentation

```yaml
# PASS: CORRECT — Payment service isolated
# docker-compose.yml
services:
  payment-service:
    networks:
      - payment-net  # Isolated network
    environment:
      - STRIPE_SECRET_KEY=${STRIPE_SECRET_KEY}

  web-app:
    networks:
      - public-net
      - payment-net  # Only service with access to payment network

networks:
  payment-net:
    internal: true  # No external access
  public-net:
```

#### Verification Steps

- [ ] Payment processing isolated from general application
- [ ] Network segmentation between payment and non-payment systems
- [ ] TLS 1.2+ enforced for all payment communications
- [ ] Firewall rules restrict access to payment infrastructure
- [ ] Regular network vulnerability scans

### 6. Logging & Audit Trail

#### PCI-Compliant Logging

```typescript
// PASS: CORRECT — Log payment events without sensitive data
function logPaymentEvent(event: {
  type: string;
  paymentIntentId: string;
  amount: number;
  status: string;
  userId: string;
}) {
  logger.info('Payment event', {
    type: event.type,
    paymentIntentId: event.paymentIntentId,
    amount: event.amount,
    status: event.status,
    userId: event.userId,
    timestamp: new Date().toISOString(),
  });
}

// FAIL: WRONG — Logging card data
logger.info('Payment', { cardNumber: card.number, cvv: card.cvv });
```

#### Verification Steps

- [ ] Payment events logged with timestamps
- [ ] No sensitive card data in any logs
- [ ] Logs retained for 12 months minimum (PCI requirement)
- [ ] Log access restricted to authorized personnel
- [ ] Log integrity protected (tamper-evident)

## Pre-Deployment PCI DSS Checklist

Before ANY production deployment handling payments:

- [ ] **Tokenization**: Client-side tokenization via Stripe Elements/Checkout
- [ ] **No Card Data**: Server never receives, processes, or stores card numbers
- [ ] **Webhooks**: All webhook endpoints verify signatures
- [ ] **HTTPS**: TLS 1.2+ on all payment endpoints
- [ ] **Storage**: Only tokens and last4 stored in database
- [ ] **Logging**: No card data in logs, errors, or debug output
- [ ] **Access Control**: Payment admin restricted to authorized users
- [ ] **Network**: Payment services isolated from general infrastructure
- [ ] **Dependencies**: Payment SDKs up to date
- [ ] **SAQ**: Self-Assessment Questionnaire completed (SAQ A for tokenization)
- [ ] **Incident Response**: Payment breach response plan documented

## Resources

- [PCI DSS v4.0 Quick Reference](https://www.pcisecuritystandards.org/document_library)
- [Stripe PCI Compliance Guide](https://stripe.com/docs/security/guide)
- [Razorpay PCI Compliance](https://razorpay.com/docs/payments/pci-dss/)
- [OWASP Payment Security](https://owasp.org/www-project-web-security-testing-guide/)

**Remember**: The safest approach to PCI compliance is scope reduction — never let card data touch your servers. Use Stripe Elements or Checkout to tokenize on the client side, and your PCI burden drops to SAQ A (the simplest level).
