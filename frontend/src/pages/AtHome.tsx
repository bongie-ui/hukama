import { useState, type FormEvent } from "react";
import { api } from "../api";
import Icon from "../components/Icon";
import PublicAssistant from "../components/PublicAssistant";
import { ErrorNote } from "../components/ui";
import { useAction } from "../hooks";
import { navigate } from "../router";

/** "Shop with your PIN": the registered phone number plus the PIN the family gave by phone opens the person's shop. */
export default function AtHome() {
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");
  const { busy, error, run } = useAction();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const r = await api.post<{ shop: string }>("/public/home/", { phone, pin });
      navigate(`/shop/${r.shop}`);
    });
  };

  return (
    <div className="give">
      <header className="give-top">
        <a className="brand" href="#/"><img src="/favicon.svg" alt="" /><span>Hukama</span></a>
      </header>
      <main className="give-main">
        <section className="give-hero">
          <span className="eyebrow">For family at home</span>
          <h1>Shop with your PIN</h1>
          <p>Enter the phone number your family registered for you and the PIN they told you on the phone. Then choose what you need from the shop.</p>
        </section>
        <form className="card stack" style={{ gap: 14 }} onSubmit={submit}>
          <div className="field">
            <label htmlFor="ah-phone">Your phone number</label>
            <input id="ah-phone" inputMode="tel" autoComplete="tel" placeholder="e.g. 077 123 4567" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="ah-pin">Your PIN</label>
            <input id="ah-pin" className="input" inputMode="numeric" autoComplete="one-time-code" maxLength={8}
              style={{ fontSize: 24, letterSpacing: ".35em" }} value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} />
          </div>
          <button className="btn primary block lg" disabled={busy || !phone || pin.length < 4}>{busy ? <span className="spinner" /> : null}Open my shop</button>
          <ErrorNote error={error} />
          <span className="xs muted row" style={{ gap: 6 }}><Icon name="lock" size={14} />
            Your family will never ask you for this PIN. After five wrong tries the shop is turned off and your family is told.</span>
          <span className="xs muted">No PIN yet? Ask your family to make one for you on Hukama.</span>
        </form>
      </main>
      <PublicAssistant />
    </div>
  );
}
