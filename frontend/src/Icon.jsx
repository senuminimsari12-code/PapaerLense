// All the small line icons used around the interface, in one place.
//
// Each icon is just a set of SVG shapes. Rather than keeping ten separate icon files,
// they all live in the `paths` object below and you pick one by name:
//
//     <Icon name="upload" size={20} />
//
// Every icon uses stroke="currentColor", which means it automatically takes the text
// colour of whatever surrounds it. That is why the icons recolour correctly inside
// buttons and error messages without any extra CSS.
//
// aria-hidden="true" hides them from screen readers. That is intentional: each icon
// sits next to real text that already says the same thing, so announcing the icon too
// would just repeat it.

const paths = {
  logo: (
    <>
      <path d="M7 3h9l4 4v13H7z" />
      <path d="M16 3v5h4M3 7v16h12M11 12h5m-5 4h5" />
    </>
  ),
  upload: (
    <>
      <path d="M12 16V3m-5 5 5-5 5 5M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" />
    </>
  ),
  file: (
    <>
      <path d="M5 3h10l4 4v14H5zM15 3v5h4M9 12h6m-6 4h6" />
    </>
  ),
  arrow: <path d="M5 12h14m-5-5 5 5-5 5" />,
  check: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12 3 3 5-6" />
    </>
  ),
  shield: (
    <>
      <path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z" />
      <path d="m8 12 3 3 5-6" />
    </>
  ),
  alert: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v6m0 3h.01" />
    </>
  ),
  text: (
    <>
      <path d="M4 5h16M4 10h16M4 15h10M4 20h13" />
    </>
  ),
  book: (
    <>
      <path d="M12 5c-3-2-6-2-10-1v15c4-1 7-1 10 1m0-15c3-2 6-2 10-1v15c-4-1-7-1-10 1V5Z" />
    </>
  ),
  chat: <path d="M21 11a9 9 0 0 1-9 9H4l-2 2V11a9 9 0 0 1 19 0Z" />,
};

export default function Icon({ name, size = 20, ...props }) {
  // `...props` passes through anything else the caller sets, such as className.
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}
