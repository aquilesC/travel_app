# Issues (local until filed on GitHub)

Specs written with gstack `/spec`. `00-epic-*` is the parent; `01`–`08` are its children.
Inside these files, `#1`–`#8` mean child numbers (01–08), not GitHub issue numbers.

To file them once `gh` is installed and authenticated (`sudo apt install gh && gh auth login`),
ask Claude to file them: it creates the epic first, then the 8 children, rewrites the child
numbers to the real GitHub issue numbers, and links them from the epic.

## v4: API-first website, Tailwind, iPhone app

- [`19-epic-v4-api-tailwind.md`](19-epic-v4-api-tailwind.md): website epic, children `20`–`30`.
- [`ios/00-epic-ios-app.md`](ios/00-epic-ios-app.md): iPhone app epic, children `ios/01`–`ios/09`.
  Inside `ios/`, `#N` means `ios/0N`; server issues are written `v4 #N`.
- Design: [`docs/designs/ios-trip-recorder.md`](../docs/designs/ios-trip-recorder.md).
