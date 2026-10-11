import { ReactNode } from "react";
import { Link } from "react-router";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="font-sans text-lg text-foreground">{title}</h2>
      {children}
    </section>
  );
}

/** A plain-language privacy page that anyone can open without logging in. It describes what the code really does. */
export function PrivacyPage() {
  return (
    <div className="min-h-screen bg-background p-4">
      <div className="mx-auto max-w-2xl space-y-6 py-8 text-sm leading-relaxed text-muted-foreground">
        <div>
          <Link to="/login" className="text-primary underline-offset-4 hover:underline">FinSight</Link>
          <h1 className="mt-2 font-sans text-3xl tracking-tight text-foreground">Privacy</h1>
          <p className="mt-1">Last updated 11 October 2026. FinSight is a personal learning and portfolio project, not a commercial service and not financial advice.</p>
        </div>

        <Section title="What is stored">
          <ul className="list-disc space-y-1 pl-5">
            <li><strong className="text-foreground">Your account:</strong> your email address and, if you use a password, a one-way scrambled form of it (Argon2). The password itself is never stored. If you use Google, your Google account id is stored instead; your Google password is never seen by FinSight.</li>
            <li><strong className="text-foreground">Your uploads:</strong> the file name and, for each row of a bank file you upload, its date, amount and description, plus the analysis computed from it (categories, unusual-transaction scores, forecasts) and any category you correct.</li>
            <li><strong className="text-foreground">Login sessions:</strong> a scrambled form of your login cookie with its creation and expiry times. Ended sessions are deleted about a week after they expire.</li>
            <li><strong className="text-foreground">Administrator actions:</strong> when an administrator disables or enables an account, who did it, to whom and when.</li>
            <li><strong className="text-foreground">Server logs:</strong> request addresses, status codes and request ids for troubleshooting. Transaction descriptions, passwords and login cookies are never written to the logs.</li>
          </ul>
        </Section>

        <Section title="What it is used for">
          <p>Only to show you your own analysis and to sign you in. Your data is not sold, shared for advertising, or used to train anything. There are no advertising or tracking scripts, and no analytics cookies.</p>
        </Section>

        <Section title="Cookies and browser storage">
          <p>One cookie keeps you logged in (it cannot be read by scripts on the page, and is only sent to this site). Your short-lived access token is kept in memory only. Your browser remembers which analysis you were looking at for the current tab only.</p>
        </Section>

        <Section title="Who handles it for the service">
          <ul className="list-disc space-y-1 pl-5">
            <li>Vercel serves the website, and Render runs the server (both in the United States).</li>
            <li>Neon hosts the database (United States, AWS us-west-2).</li>
            <li>Google, if you choose "Continue with Google": it tells FinSight your email address and a stable account id.</li>
            <li>An email service (Resend or Brevo), only if email is switched on: it receives your email address and the text of the message when you ask for a password reset or an address confirmation.</li>
          </ul>
        </Section>

        <Section title="Who can see your data">
          <p>Other users cannot. Administrators see only account facts (email, account type, how many analyses, whether signed in) and cannot open anyone's transactions or results. As with any hosted app, the person who runs the database and servers could technically read stored rows. The data is not encrypted inside the database.</p>
        </Section>

        <Section title="Deleting your data">
          <p>You can delete any analysis yourself from the app; its transactions and results are removed with it. There is no self-service "delete my account" button yet. To have your whole account removed, open an issue on the project's GitHub page (github.com/shauryaparihar/Finance-Analyzer) without including private details, and say which email address to remove.</p>
        </Section>

        <Section title="Please remember">
          <p>This is a demonstration project. Do not upload data you cannot afford to share, and use a demo or sample file where you can. The service may be stopped, reset or deleted at any time.</p>
        </Section>
      </div>
    </div>
  );
}
