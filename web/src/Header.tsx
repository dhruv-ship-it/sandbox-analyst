export function Header(): JSX.Element {
  return (
    <header className="app-header">
      <div>
        <h1>Sandbox Analyst</h1>
        <p className="tagline">
          Ask a question about a CSV. Watch an AI write, run and fix the code in an isolated
          sandbox.
        </p>
      </div>
      <nav className="app-header-links" aria-label="More information">
        <a href="https://github.com/dhruv-ship-it/sandbox-analyst" target="_blank" rel="noreferrer">
          GitHub
        </a>
        <a href="#how-it-works">How it works</a>
      </nav>
    </header>
  );
}
