/**
 * List of available font names (visit the url `/settings/appearance`).
 * This array is used to generate dynamic font classes (e.g., `font-sohne`).
 *
 * 📝 How to Add a New Font (Tailwind v4+):
 * 1. Add the font name here.
 * 2. Add the licensed webfont files or external stylesheet.
 * 3. Add the font family to `theme.css` using `@theme inline`.
 *
 * Example:
 * fonts.ts           → Add 'example' to this array.
 * theme.css          → Add the new font in the CSS, e.g.:
 *   @theme inline {
 *      // ... other font families
 *      --font-example: 'Example', var(--font-sans);
 *   }
 */
export const fonts = ['sohne', 'system'] as const
