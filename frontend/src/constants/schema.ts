import type { TFunction } from "i18next";
import { z } from "zod";

import type { AssetClass } from "@/types/strategy";

// Constants for decide_interval validation
// Crypto: 10-3600 seconds (10s to 1 hour)
// Stock: 1-60 days (converted to seconds: 86400 to 5184000)
export const DECIDE_INTERVAL_LIMITS = {
  crypto: { min: 10, max: 3600, unit: "seconds" as const },
  stock: { min: 1, max: 60, unit: "days" as const },
} as const;

// Convert days to seconds for stock asset class
export const SECONDS_PER_DAY = 86400;

export const createAiModelSchema = (t: TFunction) =>
  z.object({
    provider: z.string().min(1, t("validation.aiModel.providerRequired")),
    model_id: z.string().min(1, t("validation.aiModel.modelIdRequired")),
    api_key: z.string().min(1, t("validation.aiModel.apiKeyRequired")),
  });

const baseStep2Fields = {
  exchange_id: z.string(),
  api_key: z.string(),
  secret_key: z.string(),
  passphrase: z.string(),
  wallet_address: z.string(),
  private_key: z.string(),
};

// Step 2 Schema: Exchanges (conditional validation with superRefine)
export const createExchangeSchema = (t: TFunction) =>
  z.union([
    z.object({
      ...baseStep2Fields,
      trading_mode: z.literal("virtual"),
    }),

    // Backtest mode - no exchange credentials needed
    z.object({
      ...baseStep2Fields,
      trading_mode: z.literal("backtest"),
    }),

    // Live Trading - Hyperliquid
    z.object({
      ...baseStep2Fields,
      trading_mode: z.literal("live"),
      exchange_id: z.literal("hyperliquid"),
      wallet_address: z
        .string()
        .min(1, t("validation.exchange.walletAddressHyperliquidRequired")),
      private_key: z
        .string()
        .min(1, t("validation.exchange.privateKeyHyperliquidRequired")),
    }),

    // Live Trading - OKX & Coinbase (Require Passphrase)
    z.object({
      ...baseStep2Fields,
      trading_mode: z.literal("live"),
      exchange_id: z.enum(["okx", "coinbaseexchange"]),
      api_key: z.string().min(1, t("validation.exchange.apiKeyRequired")),
      secret_key: z.string().min(1, t("validation.exchange.secretKeyRequired")),
      passphrase: z
        .string()
        .min(1, t("validation.exchange.passphraseRequired")),
    }),

    // Live Trading - Standard Exchanges
    z.object({
      ...baseStep2Fields,
      trading_mode: z.literal("live"),
      exchange_id: z.enum(["binance", "blockchaincom", "gate", "mexc"]),
      api_key: z.string().min(1, t("validation.exchange.apiKeyRequired")),
      secret_key: z.string().min(1, t("validation.exchange.secretKeyRequired")),
    }),
  ]);

// Step 3 Schema: Trading Strategy
// assetClass determines decide_interval validation:
// - crypto: 10-3600 seconds
// - stock: 1-60 days (stored as seconds internally)
export const createTradingStrategySchema = (
  t: TFunction,
  tradingMode: "live" | "virtual" | "backtest" = "live",
  assetClass: AssetClass = "crypto",
) => {
  // Get limits based on asset class
  const limits = DECIDE_INTERVAL_LIMITS[assetClass];
  const isStock = assetClass === "stock";

  // For stock: validate in days (1-60), for crypto: validate in seconds (10-3600)
  const decideIntervalSchema = isStock
    ? z
        .number()
        .min(limits.min, t("validation.trading.decideIntervalMinDays"))
        .max(limits.max, t("validation.trading.decideIntervalMaxDays"))
    : z
        .number()
        .min(limits.min, t("validation.trading.decideIntervalMin"))
        .max(limits.max, t("validation.trading.decideIntervalMax"));

  const baseSchema = z.object({
    strategy_type: z.enum(["PromptBasedStrategy", "GridStrategy"]),
    strategy_name: z
      .string()
      .min(1, t("validation.trading.strategyNameRequired")),
    initial_capital: z
      .number()
      .min(1, t("validation.trading.initialCapitalMin")),
    max_leverage: z
      .number()
      .min(1, t("validation.trading.maxLeverageMin"))
      .max(5, t("validation.trading.maxLeverageMax")),
    symbols: z.array(z.string()).min(1, t("validation.trading.symbolsMin")),
    template_id: z.string().min(1, t("validation.trading.templateRequired")),
    decide_interval: decideIntervalSchema,
    backtest_start_ts: z.number().optional(),
    backtest_end_ts: z.number().optional(),
  });

  if (tradingMode === "backtest") {
    return baseSchema.refine(
      (data) => {
        if (!data.backtest_start_ts || !data.backtest_end_ts) {
          return false;
        }
        return data.backtest_start_ts < data.backtest_end_ts;
      },
      {
        message: t("validation.trading.backtestTimeRangeInvalid"),
        path: ["backtest_end_ts"],
      },
    );
  }

  return baseSchema;
};

// Copy strategy schema with asset class support
export const createCopyTradingStrategySchema = (
  t: TFunction,
  assetClass: AssetClass = "crypto",
) => {
  // Get limits based on asset class
  const limits = DECIDE_INTERVAL_LIMITS[assetClass];
  const isStock = assetClass === "stock";

  // For stock: validate in days (1-60), for crypto: validate in seconds (10-3600)
  const decideIntervalSchema = isStock
    ? z
        .number()
        .min(limits.min, t("validation.trading.decideIntervalMinDays"))
        .max(limits.max, t("validation.trading.decideIntervalMaxDays"))
    : z
        .number()
        .min(limits.min, t("validation.trading.decideIntervalMin"))
        .max(limits.max, t("validation.trading.decideIntervalMax"));

  return z.object({
    strategy_name: z
      .string()
      .min(1, t("validation.trading.strategyNameRequired")),
    initial_capital: z
      .number()
      .min(1, t("validation.trading.initialCapitalMin")),
    max_leverage: z
      .number()
      .min(1, t("validation.trading.maxLeverageMin"))
      .max(5, t("validation.trading.maxLeverageMax")),
    symbols: z.array(z.string()).min(1, t("validation.trading.symbolsMin")),
    decide_interval: decideIntervalSchema,
    strategy_type: z.enum(["PromptBasedStrategy", "GridStrategy"]),
    prompt_name: z.string().min(1, t("validation.copy.promptNameRequired")),
    prompt: z.string().min(1, t("validation.copy.promptRequired")),
  });
};
