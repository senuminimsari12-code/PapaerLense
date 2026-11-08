// The fixed parts of the page: header, introduction, feature list, "how it works"
// and footer.
//
// Nothing in this file has any state, props or logic. It is the same on every render,
// no matter what the user does. It lives in one file so that App.jsx contains only the
// parts that actually change, which makes the interactive logic much easier to follow.
//
// Read this file once to see what the page says, then you can ignore it.

import Icon from "./Icon.jsx";

export function SkipLink() {
  // A keyboard-only shortcut. It is invisible until focused with Tab, and lets someone
  // navigating by keyboard jump past the header straight to the workspace.
  return (
    <a className="skip-link" href="#main">
      Skip to workspace
    </a>
  );
}

export function SiteHeader() {
  return (
    <header className="site-header">
      <a className="brand" href="/" aria-label="PaperLense home">
        <span className="brand-mark">
          <Icon name="logo" size={26} />
        </span>
        <span>
          Paper<span className="brand-light">Lens</span>
          <span className="brand-dot">.</span>
        </span>
      </a>
      <div className="header-right">
        <a href="#how-it-works">
          How it works <span aria-hidden="true">↗</span>
        </a>
        <span className="phase-badge">
          PHASE 03 <span>Paper Q&A</span>
        </span>
      </div>
    </header>
  );
}

export function IntroSection() {
  return (
    <section className="intro" aria-labelledby="page-title">
      <p className="eyebrow">
        <span className="tiny-line" /> A LITTLE CLARITY FOR BIG IDEAS
      </p>
      <h1 id="page-title">
        Your research,
        <br className="mobile-break" /> <span>in focus.</span>
      </h1>
      <p className="intro-copy">
        Every great insight starts with a paper. Bring yours into a calm,
        <br className="desktop-break" /> focused workspace and explore what’s
        inside.
      </p>
      <div className="local-note">
        <Icon name="shield" size={16} /> PDF extraction stays local{" "}
        <span aria-hidden="true">·</span> Summaries and Q&A use online AI providers
      </div>
    </section>
  );
}

export function FeatureListSection() {
  return (
    <section className="next-section" aria-labelledby="next-title">
      <div className="next-intro">
        <p className="eyebrow">A FOUNDATION FOR MORE</p>
        <h2 id="next-title">
          First the paper. <br />
          Then the possibilities.
        </h2>
      </div>
      <div className="future-feature">
        <span className="feature-icon">
          <Icon name="book" size={22} />
        </span>
        <div>
          <div className="future-heading">
            <h3>Structured summaries</h3>
            <span>Available</span>
          </div>
          <p>
            From the big question to the key results,
            <br className="desktop-break" /> a clearer picture of the research.
          </p>
        </div>
      </div>
      <div className="future-feature">
        <span className="feature-icon">
          <Icon name="chat" size={21} />
        </span>
        <div>
          <div className="future-heading">
            <h3>Ask your paper</h3>
            <span>Available</span>
          </div>
          <p>
            Document-grounded answers,
            <br className="desktop-break" /> with the source always in sight.
          </p>
        </div>
      </div>
    </section>
  );
}

export function HowItWorksSection() {
  return (
    <section className="how-it-works" id="how-it-works" aria-labelledby="how-title">
      <h2 id="how-title">A simple start to better research</h2>
      <div className="steps">
        <div>
          <span>1</span>
          <p>
            <strong>Bring a paper</strong>Choose one PDF with selectable text.
          </p>
        </div>
        <div>
          <span>2</span>
          <p>
            <strong>Let the text unfold</strong>We extract text and preserve page
            numbers.
          </p>
        </div>
        <div>
          <span>3</span>
          <p>
            <strong>Take a closer look</strong>Review your preview and automatic
            summary.
          </p>
        </div>
      </div>
    </section>
  );
}

export function SiteFooter() {
  return (
    <footer>
      <span className="footer-brand">
        PaperLense<span>.</span>
      </span>
      <p>Built for curious minds. Designed for focus.</p>
      <span>Phase 3 · Grounded research Q&A</span>
    </footer>
  );
}
