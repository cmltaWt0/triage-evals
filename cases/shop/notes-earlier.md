<!-- The team's notes for the invented shop project. Comments are not sent to the agent. -->
# What the shop is

- `shop-api` is the backend, a Python service in a container. `shop-web` is the storefront, built to static files.
  `shop-deploy` holds the Helm values: production runs the image tags in `values/production.yaml`.

# What counts as carrying a component

- A tool that runs only while an image is built or a test job runs is not shipped, even when its binary stays in
  the image: the image of a CI job, the Node version that builds the front end, a linter, a test runner, `apt-get`
  or `git` in a Dockerfile or a CI job. Give it no verdict, whatever the advisory is about and whatever version
  line the tool is on.
- One exception: the repository itself pins such a tool to a version the advisory names as affected (an image
  tag, a version in a config file). Then a change in this repository fixes it: judge it, and say that it is the
  build that is exposed, not production.
- What runs in the deployed system is shipped and is judged as usual: a library the application imports, a
  service that runs in production, a host's own packages.
- When this rule leaves a tool out of an advisory, say so in that advisory's note in `checked`: where the tool
  runs, and that it is build-only.
- An earlier verdict on a tool this rule leaves out becomes `not_affected`. Its evidence says that the tool runs
  only at build or test time and that these notes give such a tool no verdict.
