import { money } from "../api";
import type { GroceryItem } from "../types";
import Icon from "./Icon";

export type Cart = Record<string, number>;

export function cartLines(cart: Cart) {
  return Object.entries(cart).filter(([, q]) => q > 0).map(([item_id, quantity]) => ({ item_id, quantity }));
}

export function cartTotal(items: GroceryItem[], cart: Cart) {
  return items.reduce((s, i) => s + Number(i.price) * (cart[i.id] ?? 0), 0);
}

/** Choose items and quantities from a store's price list, grouped by category. Prices come from the store. */
export default function ItemPicker({ items, cart, onChange, currency = "USD" }:
  { items: GroceryItem[]; cart: Cart; onChange: (cart: Cart) => void; currency?: string }) {
  const groups = items.reduce<Record<string, GroceryItem[]>>((g, i) => {
    (g[i.category || "Other"] ??= []).push(i);
    return g;
  }, {});
  const set = (id: string, q: number) => onChange({ ...cart, [id]: Math.max(0, Math.min(50, q)) });

  return (
    <div className="picker">
      {Object.entries(groups).map(([category, list]) => (
        <section key={category} className="picker-group" aria-label={category}>
          <span className="label">{category}</span>
          {list.map((i) => {
            const q = cart[i.id] ?? 0;
            return (
              <div key={i.id} className={`picker-row ${q ? "on" : ""}`}>
                <div className="main">
                  <span className="title">{i.name}</span>
                  <span className="xs muted">{i.size ? `${i.size} · ` : ""}{money(i.price, currency)}</span>
                </div>
                {q === 0 ? (
                  <button type="button" className="btn outline sm" onClick={() => set(i.id, 1)} aria-label={`Add ${i.name}`}>
                    <Icon name="plus" size={16} />Add
                  </button>
                ) : (
                  <div className="qty" role="group" aria-label={`${i.name} quantity`}>
                    <button type="button" onClick={() => set(i.id, q - 1)} aria-label={`One less ${i.name}`}>−</button>
                    <span className="num" aria-live="polite">{q}</span>
                    <button type="button" onClick={() => set(i.id, q + 1)} aria-label={`One more ${i.name}`}>+</button>
                  </div>
                )}
              </div>
            );
          })}
        </section>
      ))}
    </div>
  );
}
