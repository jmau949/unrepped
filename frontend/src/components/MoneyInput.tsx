import { useEffect, useState } from "react";

const fmt = (v: number | null) =>
  v == null || Number.isNaN(v) ? "" : v.toLocaleString("en-US");
const parse = (s: string): number | null => {
  const digits = s.replace(/[^0-9]/g, "");
  return digits === "" ? null : Number(digits);
};

/** Dollar input that displays thousands separators while editing
 * (2000000 -> "2,000,000"). Two ways to hand the number back: `onSave` fires
 * on blur when it changed, like the rest of the forms; `onChange` fires on
 * every keystroke, for the list filters that apply as you type. */
export default function MoneyInput({
  value,
  onSave,
  onChange,
  className,
  placeholder,
  "aria-label": ariaLabel,
}: {
  value: number | null;
  onSave?: (v: number | null) => void;
  onChange?: (v: number | null) => void;
  className?: string;
  placeholder?: string;
  "aria-label"?: string;
}) {
  const [text, setText] = useState(fmt(value));
  useEffect(() => setText(fmt(value)), [value]);
  return (
    <input
      type="text"
      inputMode="numeric"
      value={text}
      placeholder={placeholder}
      aria-label={ariaLabel}
      onChange={(e) => {
        const v = parse(e.target.value);
        setText(fmt(v));
        onChange?.(v);
      }}
      onBlur={() => {
        if (!onSave) return;
        const v = parse(text);
        if (v !== value) onSave(v);
      }}
      className={className}
    />
  );
}
