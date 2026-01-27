import { createFormHook, createFormHookContexts } from "@tanstack/react-form";
import {
  DateTimeField,
  NumberField,
  PasswordField,
  RadioField,
  SelectField,
  TextField,
} from "@/components/valuecell/form/field";

export const { fieldContext, useFieldContext, formContext, useFormContext } =
  createFormHookContexts();
export const { useAppForm, withForm } = createFormHook({
  fieldComponents: {
    DateTimeField,
    TextField,
    NumberField,
    PasswordField,
    SelectField,
    RadioField,
  },
  formComponents: {},
  fieldContext,
  formContext,
});
