# plots

CMS-style figures for the rest of the pipeline. Static PNG and SVG come from `upstream/cms-plotting` (matplotlib / mplhep canvases: a fit with pulls, a scan, toys, a comparison). Interactive canvases are Plotly JSON from `upstream/plotlyhep`, which mirrors mplhep and is the plot format frontend-slides already consumes. The two are meant to sit together: a figure produced here is what a slide embeds.

Style lint for a single plot is cms-plotting's `lint.py`. Extending that to the approval state of each number, the CMS label on the figure (Private work, Work in progress, Preliminary, Simulation), and a confidentiality gate is `checks/` work, not something this folder does on its own.

Only approved public results, or toy and simulated examples, belong here. This repository is public: do not add internal or unapproved CMS plots or the numbers on them.
