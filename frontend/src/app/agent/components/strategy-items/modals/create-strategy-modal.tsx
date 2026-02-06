import { useStore } from "@tanstack/react-form";
import { AlertCircleIcon } from "lucide-react";
import type { FC, RefObject } from "react";
import { memo, useEffect, useImperativeHandle, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useGetModelProviderDetail } from "@/api/setting";
import {
  useCreateStrategy,
  useGetStrategyList,
  useGetStrategyPrompts,
} from "@/api/strategy";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import CloseButton from "@/components/valuecell/button/close-button";
import { AIModelForm } from "@/components/valuecell/form/ai-model-form";
import {
  EXCHANGE_OPTIONS,
  ExchangeForm,
} from "@/components/valuecell/form/exchange-form";
import { TradingStrategyForm } from "@/components/valuecell/form/trading-strategy-form";
import { StepIndicator } from "@/components/valuecell/step-indicator";
import {
  CRYPTO_TRADING_SYMBOLS,
  STOCK_TRADING_SYMBOLS,
  TRADING_SYMBOLS,
} from "@/constants/agent";
import {
  createAiModelSchema,
  createExchangeSchema,
  createTradingStrategySchema,
  SECONDS_PER_DAY,
} from "@/constants/schema";
import { useAppForm } from "@/hooks/use-form";
import { tracker } from "@/lib/tracker";
import type {
  AssetClass,
  CreateStrategy,
  Strategy,
  TradingMode,
} from "@/types/strategy";

export interface CreateStrategyModelRef {
  open: (data?: CreateStrategy) => void;
}
interface CreateStrategyModalProps {
  children?: React.ReactNode;
  ref?: RefObject<CreateStrategyModelRef | null>;
}

const CreateStrategyModal: FC<CreateStrategyModalProps> = ({
  ref,
  children,
}) => {
  const { t } = useTranslation();
  const aiModelSchema = useMemo(() => createAiModelSchema(t), [t]);
  const exchangeSchema = useMemo(() => createExchangeSchema(t), [t]);
  const [open, setOpen] = useState(false);
  const [currentStep, setCurrentStep] = useState(1);
  const [error, setError] = useState<string | null>(null);

  const STEPS = [
    { step: 1, title: t("strategy.create.steps.aiModels") },
    { step: 2, title: t("strategy.create.steps.exchanges") },
    { step: 3, title: t("strategy.create.steps.tradingStrategy") },
  ];

  const { data: strategies = [] } = useGetStrategyList();
  const { mutateAsync: createStrategy, isPending: isCreatingStrategy } =
    useCreateStrategy();

  // Step 1 Form: AI Models
  const form1 = useAppForm({
    defaultValues: {
      provider: "",
      model_id: "",
      api_key: "",
    },
    validators: {
      onSubmit: aiModelSchema,
    },
    onSubmit: () => {
      setCurrentStep(2);
    },
  });

  const provider = useStore(form1.store, (state) => state.values.provider);
  const { data: modelProviderDetail } = useGetModelProviderDetail(provider);

  // Step 2 Form: Exchanges
  const form2 = useAppForm({
    defaultValues: {
      trading_mode: "live" as TradingMode,
      asset_class: "crypto" as AssetClass,
      exchange_id: "okx",
      api_key: "",
      secret_key: "",
      passphrase: "",
      wallet_address: "",
      private_key: "",
    },
    validators: {
      onSubmit: exchangeSchema,
    },
    onSubmit: () => {
      const modelId = form1.state.values.model_id;
      const modelName =
        modelProviderDetail?.models.find((m) => m.model_id === modelId)
          ?.model_name || modelId;

      const { trading_mode, exchange_id } = form2.state.values;
      const exchangeName =
        trading_mode === "virtual"
          ? "Virtual"
          : trading_mode === "backtest"
            ? "Backtest"
            : EXCHANGE_OPTIONS.find((ex) => ex.value === exchange_id)?.label ||
              exchange_id;

      const baseName = `${modelName}-${exchangeName}`;
      let newName = baseName;
      let counter = 1;

      while (strategies.some((s) => s.strategy_name === newName)) {
        newName = `${baseName}-${counter}`;
        counter++;
      }

      form3.setFieldValue("strategy_name", newName);

      // Set default symbols based on asset class
      const { asset_class } = form2.state.values;
      const defaultSymbols =
        asset_class === "stock" ? STOCK_TRADING_SYMBOLS : CRYPTO_TRADING_SYMBOLS;
      form3.setFieldValue("symbols", defaultSymbols);

      // Reset template_id when asset class changes (prompts are filtered by asset class)
      form3.setFieldValue("template_id", "");

      // Set default decide_interval based on asset class
      // Crypto: 60 seconds, Stock: 1 day
      const defaultDecideInterval = asset_class === "stock" ? 1 : 60;
      form3.setFieldValue("decide_interval", defaultDecideInterval);

      setCurrentStep(3);
    },
  });

  // Get asset class from form2 for filtering prompts
  const assetClass = useStore(
    form2.store,
    (state) => state.values.asset_class,
  );

  // Get prompts filtered by asset class when in virtual/backtest mode
  const tradingModeForPrompts = useStore(
    form2.store,
    (state) => state.values.trading_mode,
  );
  const { data: prompts = [] } = useGetStrategyPrompts(
    tradingModeForPrompts !== "live" ? assetClass : undefined,
  );

  // Get trading mode for schema validation
  const tradingMode = useStore(
    form2.store,
    (state) => state.values.trading_mode,
  );

  // Create trading strategy schema with trading mode and asset class
  const tradingStrategySchema = useMemo(
    () => createTradingStrategySchema(t, tradingMode, assetClass),
    [t, tradingMode, assetClass],
  );

  // Step 3 Form: Trading Strategy
  const form3 = useAppForm({
    defaultValues: {
      strategy_type: "PromptBasedStrategy" as Strategy["strategy_type"],
      strategy_name: "",
      initial_capital: 1000,
      max_leverage: 2,
      decide_interval: 60,
      symbols: TRADING_SYMBOLS,
      template_id: "",
      backtest_start_ts: undefined as number | undefined,
      backtest_end_ts: undefined as number | undefined,
    },
    validators: {
      onSubmit: tradingStrategySchema,
    },
    onSubmit: async ({ value }) => {
      // Convert decide_interval from days to seconds for stock asset class
      const { asset_class } = form2.state.values;
      const decideIntervalInSeconds =
        asset_class === "stock"
          ? value.decide_interval * SECONDS_PER_DAY
          : value.decide_interval;

      const payload = {
        llm_model_config: form1.state.values,
        exchange_config: form2.state.values,
        trading_config: {
          ...value,
          decide_interval: decideIntervalInSeconds,
        },
      };

      const { code, msg } = await createStrategy(payload);
      if (code !== 0) {
        setError(msg);
        return;
      }

      tracker.send("use", { agent_name: "StrategyAgent" });
      resetAll();
    },
  });

  // Auto-select first prompt when prompts are loaded and template_id is empty
  useEffect(() => {
    if (
      currentStep === 3 &&
      prompts.length > 0 &&
      !form3.state.values.template_id
    ) {
      form3.setFieldValue("template_id", prompts[0].id);
    }
  }, [currentStep, prompts, form3.state.values.template_id]);

  const resetAll = () => {
    setCurrentStep(1);
    form1.reset();
    form2.reset();
    form3.reset();
    setError(null);
    setOpen(false);
  };

  const handleBack = () => {
    if (currentStep > 1) {
      setCurrentStep((prev) => prev - 1);
    }
  };

  useImperativeHandle(ref, () => ({
    open: (data) => {
      if (data) {
        form1.reset(data.llm_model_config);
        form2.reset(data.exchange_config);
        form3.reset(data.trading_config);
      }
      setOpen(true);
    },
  }));

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{children}</DialogTrigger>

      <DialogContent
        className="flex max-h-[90vh] min-h-96 flex-col"
        showCloseButton={false}
        aria-describedby={undefined}
      >
        <DialogTitle className="flex flex-col gap-4 px-1">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-lg">
              {t("strategy.create.title")}
            </h2>
            <CloseButton onClick={resetAll} />
          </div>

          <StepIndicator steps={STEPS} currentStep={currentStep} />
        </DialogTitle>

        {/* Form content with scroll */}
        <div className="scroll-container px-1 py-2">
          {/* Step 1: AI Models */}
          {currentStep === 1 && <AIModelForm form={form1} />}

          {/* Step 2: Exchanges */}
          {currentStep === 2 && <ExchangeForm form={form2} />}

          {/* Step 3: Trading Strategy */}
          {currentStep === 3 && (
            <TradingStrategyForm
              form={form3}
              prompts={prompts}
              tradingMode={form2.state.values.trading_mode}
              assetClass={form2.state.values.asset_class}
            />
          )}
        </div>

        <DialogFooter className="mt-auto flex flex-col! gap-2">
          {error && (
            <Alert variant="destructive">
              <AlertCircleIcon />
              <AlertTitle>{t("strategy.create.error")}</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="grid w-full grid-cols-2 gap-4">
            <Button
              type="button"
              variant="outline"
              onClick={currentStep === 1 ? resetAll : handleBack}
              className="py-4 font-semibold text-base"
            >
              {currentStep === 1
                ? t("strategy.action.cancel")
                : t("strategy.action.back")}
            </Button>
            <Button
              type="button"
              disabled={isCreatingStrategy}
              onClick={async () => {
                switch (currentStep) {
                  case 1:
                    await form1.handleSubmit();
                    break;
                  case 2:
                    await form2.handleSubmit();
                    break;
                  case 3:
                    await form3.handleSubmit();
                }
              }}
              className="relative py-4 font-semibold text-base"
            >
              {isCreatingStrategy && <Spinner className="absolute left-4" />}
              {currentStep === 3
                ? t("strategy.action.confirm")
                : t("strategy.action.next")}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default memo(CreateStrategyModal);
