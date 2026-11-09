// Header, introduction, usage guide, and footer.

import Icon from "./Icon.jsx";
import { PreferenceControls, useTranslation } from "./interfacePreferences.jsx";

export function SkipLink() {
  const t = useTranslation();
  // A keyboard-only shortcut. It is invisible until focused with Tab, and lets someone
  // navigating by keyboard jump past the header straight to the workspace.
  return (
    <a className="skip-link" href="#main">{t("Skip to workspace")}</a>
  );
}

export function SiteHeader({ preferences }) {
  const t = useTranslation();
  return (
    <header className="site-header">
      <a className="brand" href="/" aria-label={t("PaperLense home")}>
        <span className="brand-mark">
          <Icon name="logo" size={26} />
        </span>
        <span>
          Paper<span className="brand-light">Lens</span>
          <span className="brand-dot">.</span>
        </span>
      </a>
      <div className="header-right">
        <a href="#how-it-works">{t("How it works")}{" "}<span aria-hidden="true">↗</span>
        </a>
        <span className="phase-badge">{t("PHASE 03")}{" "}<span>{t("Paper Q&A")}</span>
        </span>
        <PreferenceControls {...preferences} />
      </div>
    </header>
  );
}

export function IntroSection() {
  const t = useTranslation();
  return (
    <section className="intro" aria-labelledby="page-title">
      <p className="eyebrow"><span className="tiny-line" />{" "}{t("A LITTLE CLARITY FOR BIG IDEAS")}</p>
      <h1 id="page-title">{t("Your research,")}<br className="mobile-break" /> <span>{t("in focus.")}</span></h1>
      <p className="intro-copy">
        {t("Every great insight starts with a paper. Bring yours into a calm, focused workspace and explore what’s inside.")}
      </p>
      <div className="local-note">
        <Icon name="shield" size={16} />{" "}{t("PDF extraction stays local")}{" "}
        <span aria-hidden="true">·</span>{" "}{t("Summaries and Q&A use online AI providers")}</div>
    </section>
  );
}

export function FeatureListSection() {
  const t = useTranslation();
  return (
    <section className="next-section" aria-labelledby="next-title">
      <div className="next-intro">
        <p className="eyebrow">{t("A FOUNDATION FOR MORE")}</p>
        <h2 id="next-title">
          {t("First the paper.")} <br />
          {t("Then the possibilities.")}
        </h2>
      </div>
      <div className="future-feature">
        <span className="feature-icon">
          <Icon name="book" size={22} />
        </span>
        <div>
          <div className="future-heading">
            <h3>{t("Structured summaries")}</h3>
            <span>{t("Available")}</span>
          </div>
          <p>
            {t("From the big question to the key results, a clearer picture of the research.")}
          </p>
        </div>
      </div>
      <div className="future-feature">
        <span className="feature-icon">
          <Icon name="chat" size={21} />
        </span>
        <div>
          <div className="future-heading">
            <h3>{t("Ask your paper")}</h3>
            <span>{t("Available")}</span>
          </div>
          <p>
            {t("Document-grounded answers, with the source always in sight.")}
          </p>
        </div>
      </div>
    </section>
  );
}

export function HowItWorksSection() {
  const t = useTranslation();
  return (
    <section className="how-it-works" id="how-it-works" aria-labelledby="how-title">
      <h2 id="how-title">{t("A simple start to better research")}</h2>
      <div className="steps">
        <div>
          <span>1</span>
          <p>
            <strong>{t("Bring a paper")}</strong>{t("Choose one PDF with selectable text.")}</p>
        </div>
        <div>
          <span>2</span>
          <p>
            <strong>{t("Let the text unfold")}</strong>{t("We extract text and preserve page numbers.")}</p>
        </div>
        <div>
          <span>3</span>
          <p>
            <strong>{t("Take a closer look")}</strong>{t("Review your preview and automatic summary.")}</p>
        </div>
      </div>
    </section>
  );
}

export function SiteFooter() {
  const t = useTranslation();
  return (
    <footer>
      <span className="footer-brand">
        PaperLense<span>.</span>
      </span>
      <p>{t("Built for curious minds. Designed for focus.")}</p>
      <span>{t("Phase 3 · Grounded research Q&A")}</span>
    </footer>
  );
}
