import type { FC } from "react";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useFieldContext } from "@/hooks/use-form";

type DateTimeFieldProps = {
  label: string;
  className?: string;
};

export const DateTimeField: FC<DateTimeFieldProps> = ({ label, className }) => {
  const field = useFieldContext<number | undefined>();

  // Convert timestamp (ms) to datetime-local format
  const formatTimestamp = (ts: number | undefined): string => {
    if (!ts) return "";
    const date = new Date(ts);
    // Format: YYYY-MM-DDTHH:mm
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    const hours = String(date.getHours()).padStart(2, "0");
    const minutes = String(date.getMinutes()).padStart(2, "0");
    return `${year}-${month}-${day}T${hours}:${minutes}`;
  };

  // Convert datetime-local value to timestamp (ms)
  const parseDateTime = (value: string): number | undefined => {
    if (!value) return undefined;
    return new Date(value).getTime();
  };

  return (
    <Field className={className}>
      <FieldLabel className="font-medium text-base text-foreground">
        {label}
      </FieldLabel>
      <Input
        type="datetime-local"
        value={formatTimestamp(field.state.value)}
        onChange={(e) => field.handleChange(parseDateTime(e.target.value))}
        onBlur={field.handleBlur}
      />
      <FieldError errors={field.state.meta.errors} />
    </Field>
  );
};
