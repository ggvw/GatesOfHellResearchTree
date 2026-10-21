# Deploying a release to GitHub Pages

[Back to the project](../README.md)

[The Pages workflow](../.github/workflows/deploy-pages.yml) deploys the
`research_tree_html.zip` asset from each newly published stable GitHub Release.
It skips prereleases and does not run on pushes. It downloads the triggering
release's asset, validates it, and uploads the extracted files using GitHub's
official Pages actions. It does not regenerate or commit game data.

Set up the repository once:

1. Under **Settings → Pages → Build and deployment**, select **GitHub Actions**
   as the source.
2. Ensure **Settings → Actions → General** allows GitHub Actions and the official
   `actions/configure-pages`, `actions/upload-pages-artifact`, and
   `actions/deploy-pages` actions.
3. Under **Settings → Environments → github-pages**, ensure deployment rules allow
   release **tags**, such as `V*`. A rule allowing only `main` will block releases.
   Remove required reviewers if deployments should proceed without approval.

Include the workflow in the commit targeted by the next release tag. Attach the
ZIP to the draft release **before publishing**. Its contents must start with
`index.html` and `assets/`, not a wrapping `research_tree_html/` directory. Relative
paths such as `assets/...` are preserved. Missing ZIPs, invalid archives, or missing
root `index.html` files fail with a clear error. After correcting an asset, rerun
the failed workflow from the Actions tab.

No additional secrets or personal access token are required for this deployment.
The download job has `contents: read`; only the deployment job has `pages: write`
and `id-token: write`.

Publish the release through GitHub's UI or an authenticated user/App. GitHub does
not trigger another workflow for releases created by a workflow's `GITHUB_TOKEN`;
this is separate from the default token used to download and deploy the site.
See [GitHub's token event rules](https://docs.github.com/en/actions/concepts/security/github_token).
