import { MultiSelect } from "@valuecell/multi-select";
import { useTranslation } from "react-i18next";
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field";
import { SelectItem } from "@/components/ui/select";
import {
  CRYPTO_TRADING_SYMBOLS,
  STOCK_TRADING_SYMBOLS,
  TRADING_SYMBOLS,
} from "@/constants/agent";
import { DECIDE_INTERVAL_LIMITS } from "@/constants/schema";
import { withForm } from "@/hooks/use-form";
import type { AssetClass, Strategy } from "@/types/strategy";

export const CopyStrategyForm = withForm({
  defaultValues: {
    strategy_type: "" as Strategy["strategy_type"],
    strategy_name: "",
    initial_capital: 1000,
    max_leverage: 2,
    decide_interval: 60,
    symbols: TRADING_SYMBOLS,
    prompt_name: "",
    prompt: "",
  },
  props: {
    tradingMode: "live" as "live" | "virtual",
    assetClass: "crypto" as AssetClass,
  },
  render({ form, tradingMode, assetClass }) {
    const { t } = useTranslation();

    // Get symbols based on asset class
    const defaultSymbols =
      assetClass === "stock" ? STOCK_TRADING_SYMBOLS : CRYPTO_TRADING_SYMBOLS;
    return (
      <FieldGroup className="gap-6">
        <form.AppField
          listeners={{
            onChange: ({ value }: { value: Strategy["strategy_type"] }) => {
              if (value === "GridStrategy") {
                form.setFieldValue("symbols", [defaultSymbols[0]]);
              } else {
                form.setFieldValue("symbols", defaultSymbols);
              }
            },
          }}
          name="strategy_type"
        >
          {(field) => (
            <field.SelectField label={t("strategy.form.strategyType.label")}>
              <SelectItem value="PromptBasedStrategy">
                {t("strategy.form.strategyType.promptBased")}
              </SelectItem>
              {/* Hide GridStrategy for US Stocks */}
              {assetClass !== "stock" && (
                <SelectItem value="GridStrategy">
                  {t("strategy.form.strategyType.grid")}
                </SelectItem>
              )}
            </field.SelectField>
          )}
        </form.AppField>

        <form.AppField name="strategy_name">
          {(field) => (
            <field.TextField
              label={t("strategy.form.strategyName.label")}
              placeholder={t("strategy.form.strategyName.placeholder")}
            />
          )}
        </form.AppField>

        <FieldGroup className="flex flex-row gap-4">
          {tradingMode === "virtual" && (
            <form.AppField name="initial_capital">
              {(field) => (
                <field.NumberField
                  className="flex-1"
                  label={t("strategy.form.initialCapital.label")}
                  placeholder={t("strategy.form.initialCapital.placeholder")}
                />
              )}
            </form.AppField>
          )}

          <form.AppField name="max_leverage">
            {(field) => (
              <field.NumberField
                className="flex-1"
                label={t("strategy.form.maxLeverage.label")}
                placeholder={t("strategy.form.maxLeverage.placeholder")}
              />
            )}
          </form.AppField>
        </FieldGroup>

        <form.AppField name="decide_interval">
          {(field) => {
            const isStock = assetClass === "stock";
            const limits = DECIDE_INTERVAL_LIMITS[assetClass];
            return (
              <field.NumberField
                label={
                  isStock
                    ? t("strategy.form.decideInterval.labelDays")
                    : t("strategy.form.decideInterval.label")
                }
                placeholder={
                  isStock
                    ? t("strategy.form.decideInterval.placeholderDays", {
                        min: limits.min,
                        max: limits.max,
                      })
                    : t("strategy.form.decideInterval.placeholder")
                }
              />
            );
          }}
        </form.AppField>

        <form.Subscribe selector={(state) => state.values.strategy_type}>
          {(strategyType) => {
            return (
              <form.Field name="symbols">
                {(field) => (
                  <Field>
                    <FieldLabel className="font-medium text-base text-foreground">
                      {t("strategy.form.tradingSymbols.label")}
                    </FieldLabel>
                    <MultiSelect
                      maxSelected={
                        strategyType === "GridStrategy" ? 1 : undefined
                      }
                      options={defaultSymbols}
                      value={field.state.value}
                      onValueChange={(value) => field.handleChange(value)}
                      placeholder={t("strategy.form.tradingSymbols.placeholder")}
                      searchPlaceholder={t(
                        "strategy.form.tradingSymbols.searchPlaceholder",
                      )}
                      emptyText={t("strategy.form.tradingSymbols.emptyText")}
                      maxDisplayed={5}
                      creatable
                    />
                    <FieldError errors={field.state.meta.errors} />
                  </Field>
                )}
              </form.Field>
            );
          }}
        </form.Subscribe>

        <form.Subscribe selector={(state) => state.values.strategy_type}>
          {(strategyType) => {
            return (
              strategyType === "PromptBasedStrategy" && (
                <form.Field name="prompt">
                  {(field) => (
                    <Field>
                      <FieldLabel className="font-medium text-base text-foreground">
                        {t("strategy.form.promptTemplate.label")}
                      </FieldLabel>
                      <div className="text-muted-foreground text-sm">
                        {field.state.value}
                      </div>
                      <FieldError errors={field.state.meta.errors} />
                    </Field>
                  )}
                </form.Field>
              )
            );
          }}
        </form.Subscribe>
      </FieldGroup>
    );
  },
});
