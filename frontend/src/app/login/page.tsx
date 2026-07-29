import Link from 'next/link';

export default function LoginPage(): JSX.Element {
  return (
    <main className="grid min-h-screen place-items-center p-6">
      <section className="w-full max-w-md rounded-2xl border border-zinc-800 bg-zinc-900/60 p-8 shadow-2xl shadow-black/20 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-cyan-500/10">
            <svg className="h-5 w-5 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
            </svg>
          </span>
          <div>
            <h1 className="text-xl font-semibold text-zinc-100">Sentinel<span className="text-cyan-400">-IQ</span></h1>
            <p className="text-xs text-zinc-500">Cloud governance operations console</p>
          </div>
        </div>
        <div className="mt-8">
          <h2 className="text-lg font-semibold text-zinc-100">Sign in</h2>
          <p className="mt-2 text-sm text-zinc-400">Authentication is provided by the configured identity service. Contact your security administrator for access.</p>
        </div>
        <div className="mt-6 space-y-3">
          <Link href="/" className="flex w-full items-center justify-center rounded-xl border border-cyan-500/40 bg-cyan-500/10 px-4 py-3 text-sm font-semibold text-cyan-300 transition hover:bg-cyan-500/20">
            Return to dashboard
          </Link>
        </div>
        <p className="mt-6 text-center text-xs text-zinc-500">Sentinel-IQ v0.1.0 · Enterprise AWS Governance</p>
      </section>
    </main>
  );
}
