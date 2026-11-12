// Bitmap font renderer for the Xbox 'font file' format (public/ui/fonts/<name>.json + atlas PNG): drawText(ctx, text, x, y, scale)
export class BitmapFont {
  constructor(json, image) { this.f = json; this.img = image; this.map = new Map(json.glyphs.map((g) => [g.char, g])); }
  static async load(name) {
    const json = await (await fetch(`/public/ui/fonts/${name}.json`)).json();
    const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = `/public/ui/${name}.png`; });
    return new BitmapFont(json, img);
  }
  width(text, scale = 1, tracking = 0) { let w = 0; for (const ch of text) { const g = this.map.get(ch) || this.map.get('?'); if (g) w += (g.advance + tracking) * scale; } return w; }   // tracking: extra source pixels after every glyph
  draw(ctx, text, x, y, scale = 1, align = 'left', tracking = 0) {   // y = baseline-ish top of the cell
    if (align !== 'left') x -= this.width(text, scale, tracking) * (align === 'center' ? 0.5 : 1);
    for (const ch of text) {
      const g = this.map.get(ch) || this.map.get('?'); if (!g) continue;
      if (g.gw > 0 && g.gh > 0) ctx.drawImage(this.img, g.x, g.y, g.gw, g.gh, Math.round(x + g.gx * scale), Math.round(y + g.gy * scale), g.gw * scale, g.gh * scale);   // source = (bmofsx, bmofsy, glyphwidth, glyphheight); glyphofs is the pen offset
      x += (g.advance + tracking) * scale;
    }
  }
}
