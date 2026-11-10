// The Evidence Explorer's wording, in the three languages PaperLens supports.
//
// Only the interface labels are translated. The passages themselves are never
// translated: they are the research paper's own words, and changing them would stop
// them being evidence.
//
// {count}, {number} and {page} are filled in by fillLabel() from translations.js.

export function fillLabel(template, values) {
  return template.replace(/\{(\w+)\}/g, (placeholder, key) => values[key] ?? placeholder);
}

export const EVIDENCE_LABELS = {
  en: {
    title: "Evidence Explorer",
    supportingPassage: "{count} supporting passage",
    supportingPassages: "{count} supporting passages",
    retrievedPassage: "{count} retrieved passage",
    retrievedPassages: "{count} retrieved passages",
    note:
      "These are the passages PaperLens retrieved from your PDF and sent to the AI. " +
      "They show what the answer was based on; they are not a fact-check of it.",
    source: "Source {number}",
    page: "Page {page}",
    cited: "Cited in the answer",
    notCited: "Retrieved, not cited",
    openSource: "Open source",
    openSourcePage: "Open source page {page} in the document preview",
    pageNotInPreview: "Page {page} is beyond the extracted-text preview",
  },
  si: {
    title: "සාක්ෂි ගවේෂකය",
    supportingPassage: "සහාය දක්වන ඡේද {count}",
    supportingPassages: "සහාය දක්වන ඡේද {count}",
    retrievedPassage: "ලබාගත් ඡේද {count}",
    retrievedPassages: "ලබාගත් ඡේද {count}",
    note:
      "මේවා PaperLens ඔබගේ PDF එකෙන් ලබාගෙන AI වෙත යැවූ ඡේද වේ. " +
      "පිළිතුර පදනම් වූයේ කුමක් මතද යන්න ඒවා පෙන්වයි; ඒවා පිළිතුරේ සත්‍යතා පරීක්ෂණයක් නොවේ.",
    source: "මූලාශ්‍රය {number}",
    page: "පිටුව {page}",
    cited: "පිළිතුරේ උපුටා දක්වා ඇත",
    notCited: "ලබාගත්, උපුටා දක්වා නැත",
    openSource: "මූලාශ්‍රය විවෘත කරන්න",
    openSourcePage: "ලේඛන පෙරදසුනේ {page} පිටුව විවෘත කරන්න",
    pageNotInPreview: "{page} පිටුව උපුටාගත් පෙළ පෙරදසුනෙන් පිටතය",
  },
  ta: {
    title: "சான்று ஆய்வு",
    supportingPassage: "{count} ஆதரவுப் பகுதி",
    supportingPassages: "{count} ஆதரவுப் பகுதிகள்",
    retrievedPassage: "{count} மீட்டெடுக்கப்பட்ட பகுதி",
    retrievedPassages: "{count} மீட்டெடுக்கப்பட்ட பகுதிகள்",
    note:
      "இவை PaperLens உங்கள் PDF இலிருந்து மீட்டெடுத்து AI க்கு அனுப்பிய பகுதிகள். " +
      "பதில் எதன் அடிப்படையில் உருவானது என்பதை இவை காட்டுகின்றன; இவை பதிலின் உண்மைச் சரிபார்ப்பு அல்ல.",
    source: "ஆதாரம் {number}",
    page: "பக்கம் {page}",
    cited: "பதிலில் மேற்கோள் காட்டப்பட்டது",
    notCited: "மீட்டெடுக்கப்பட்டது, மேற்கோள் இல்லை",
    openSource: "ஆதாரத்தைத் திறக்க",
    openSourcePage: "ஆவண முன்தோற்றத்தில் பக்கம் {page} ஐத் திறக்க",
    pageNotInPreview: "பக்கம் {page} பிரித்தெடுக்கப்பட்ட உரை முன்தோற்றத்திற்கு அப்பால் உள்ளது",
  },
};

// Pick one language's labels. An unknown or missing language falls back to English,
// so the Evidence Explorer always has something readable to show.
export function labelsForLanguage(language) {
  return EVIDENCE_LABELS[language] || EVIDENCE_LABELS.en;
}

// The heading that says how many passages there are.
//
// An answer that cites evidence gets "supporting passages". An honest "not enough
// evidence" answer gets "retrieved passages" instead, because those passages were
// retrieved but did not support an answer. Calling them supporting would overstate
// what they show.
export function passageCountLabel(labels, count, insufficientEvidence) {
  if (insufficientEvidence) {
    const template = count === 1 ? labels.retrievedPassage : labels.retrievedPassages;
    return fillLabel(template, { count });
  }

  const template = count === 1 ? labels.supportingPassage : labels.supportingPassages;
  return fillLabel(template, { count });
}
