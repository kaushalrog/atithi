import { useEffect, useRef, useState } from "react";

const LINKS = [
  { href: "#product", label: "Product" },
  { href: "#how", label: "How it works" },
  { href: "#businesses", label: "Businesses" },
  { href: "#trust", label: "Trust" },
];

export function Mark({ size = 28 }: { size?: number }) {
  // The Atithi mark from web/logo.svg: a microphone on the accent tile.
  return (
    <svg width={size} height={size} viewBox="0 0 88 88" aria-hidden="true" focusable="false">
      <rect width="88" height="88" rx="20" fill="var(--teal)" />
      <g fill="none" stroke="#fff" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round">
        <rect x="34.5" y="18" width="19" height="34" rx="9.5" />
        <path d="M25 43a19 19 0 0 0 38 0" />
        <path d="M44 62v10M35 72h18" />
      </g>
    </svg>
  );
}

export function Nav() {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setOpen(false); button.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <header className="nav">
      <div className="wrap nav-inner">
        <a href="#top" className="brand" aria-label="Atithi, back to top">
          <Mark /> <span>Atithi</span>
        </a>
        <button
          ref={button}
          type="button"
          className="menu-btn js-only"
          aria-expanded={open}
          aria-controls="nav-links"
          onClick={() => setOpen((o) => !o)}
        >
          <span className="sr-only">{open ? "Close menu" : "Open menu"}</span>
          <span className="menu-icon" aria-hidden="true" data-open={open} />
        </button>
        <nav id="nav-links" className="nav-links" data-open={open} aria-label="Main">
          <ul>
            {LINKS.map((l) => (
              <li key={l.href}><a href={l.href} onClick={() => setOpen(false)}>{l.label}</a></li>
            ))}
          </ul>
          <a href="#pilot" className="btn btn-ink btn-small" onClick={() => setOpen(false)}>
            Request a pilot
          </a>
        </nav>
      </div>
    </header>
  );
}
