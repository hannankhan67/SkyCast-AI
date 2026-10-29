/**
 * SkyCast AI — Stripe Checkout frontend.
 *
 * Wires the pricing page's "Upgrade to Premium" button to POST
 * /api/billing/checkout and redirect to Stripe's hosted payment page.
 *
 * Degrades gracefully: when the server reports billing is unconfigured
 * (503 + demo_available) the caller's `onDemo` hook runs instead, so the
 * app still works without Stripe keys.
 */
const Billing = (() => {
  'use strict';

  async function startCheckout(options) {
    const opts = options || {};
    const next = opts.next || '/maps';

    let res;
    try {
      res = await fetch('/api/billing/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ next: next })
      });
    } catch (err) {
      console.error('Billing: network error', err);
      return { ok: false, reason: 'network', message: 'Network error. Please try again.' };
    }

    let data = {};
    try {
      data = await res.json();
    } catch (err) {
      console.error('Billing: malformed response', err);
      return { ok: false, reason: 'bad_response', message: 'Unexpected server response.' };
    }

    if (res.ok && data.url) {
      window.location.href = data.url;
      return { ok: true, redirecting: true };
    }

    if (res.status === 503 && data.demo_available) {
      return { ok: false, reason: 'unconfigured', message: data.error || 'Billing is not configured.' };
    }

    return { ok: false, reason: 'error', message: data.error || 'Could not start checkout.' };
  }

  return { startCheckout: startCheckout };
})();
