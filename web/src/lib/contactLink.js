/**
 * Build a /contact URL with intent, product, and CTA tracking params.
 * Usage: contactLink({ intent: 'sales', product: 'aether_cloud', cta: 'pricing_team' })
 * → "/contact?intent=sales&product=aether_cloud&cta=pricing_team"
 */
export const contactLink = ({ intent, product, cta }) => {
  const p = new URLSearchParams();
  if (intent)  p.set("intent", intent);
  if (product) p.set("product", product);
  if (cta)     p.set("cta", cta);
  return `/contact?${p.toString()}`;
};
