# checks

CMS rules as checks, not as text in a prompt. Nothing in `video/` should be treated as publishable until these pass.

- The label on each stage: Private work, Work in progress, Preliminary, or Simulation.
- The approval state of every number that is shown or spoken.
- A confidentiality gate, so an internal plot cannot be muxed into a public video.
- Style lint extended from cms-plotting's `lint.py` across the whole deck and the video, not only the figure.
- A claim check: every number traces to a file such as a fit output or a datacard.

Later, evaluation can adapt Paper2Video's PresentQuiz and Code2Video's TeachQuiz into a smaller question: after watching, can a CMS colleague answer a set of questions about the analysis?

These checks decide whether a public export is allowed. They do not relax the rule that internal or unapproved CMS material is never committed to this repository.
