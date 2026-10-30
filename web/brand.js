// Applies BRAND_NAME / BRAND_ACCENT / BRAND_LOGO_URL from /api/brand to any page that includes it.
// Elements: [data-brand-name], [data-brand-tagline], .brand-mark (logo replaces the default mark).
window.brandReady = (async () => {
  'use strict';
  let brand = { name: 'HANDCAM', tagline: 'Match integrity check', accent: '#FFB000', logoUrl: null };
  try {
    const r = await fetch('/api/brand');
    if (r.ok) brand = { ...brand, ...(await r.json()) };
  } catch {
    // offline: keep defaults
  }
  const root = document.documentElement.style;
  root.setProperty('--accent', brand.accent);
  // Dark or light text on the accent, whichever reads better.
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(brand.accent.slice(i, i + 2), 16));
  root.setProperty('--accent-ink', 0.299 * r + 0.587 * g + 0.114 * b > 150 ? '#120c00' : '#ffffff');
  for (const el of document.querySelectorAll('[data-brand-name]')) el.textContent = brand.name;
  for (const el of document.querySelectorAll('[data-brand-tagline]')) el.textContent = brand.tagline;
  if (brand.bgUrl) root.setProperty('--brand-bg', `url("${encodeURI(brand.bgUrl)}")`);
  if (brand.logoUrl) {
    for (const mark of document.querySelectorAll('.brand-mark')) {
      const img = new Image();
      img.alt = '';
      img.src = brand.logoUrl;
      mark.replaceChildren(img);
      mark.classList.add('has-logo');
    }
  }
  const page = document.title;
  document.title = page ? `${page} · ${brand.name}` : brand.name;
  return brand;
})();
