function normalizeApiChatContentText(value) {
  if (typeof value === "string") return normalizeText(value);
  if (Array.isArray(value)) {
    return value
      .map(normalizeApiChatContentText)
      .filter(Boolean)
      .join("\n")
      .trim();
  }
  if (!value || typeof value !== "object") return normalizeText(value);

  const nested = value.text ?? value.content ?? value.input_text ?? value.output_text;
  if (nested !== undefined) return normalizeApiChatContentText(nested);
  return "";
}

function normalizeApiChatMessageText(rawMessage) {
  const text = normalizeApiChatContentText(rawMessage?.text);
  return text || normalizeApiChatContentText(rawMessage?.content);
}

function normalizeApiChatMessage(rawMessage) {
  const role = rawMessage?.role === "user" ? "user" : rawMessage?.role === "assistant" ? "assistant" : rawMessage?.role === "divider" ? "divider" : "";
  if (!role) return null;
  const toolCalls = Array.isArray(rawMessage?.tool_calls)
    ? rawMessage.tool_calls
    : Array.isArray(rawMessage?.toolCalls)
      ? rawMessage.toolCalls
      : [];
  if (role === "assistant" && toolCalls.length) return null;
  const text = normalizeApiChatMessageText(rawMessage);
  const attachments = normalizeImageArtifacts(rawMessage?.attachments);
  const artifacts = normalizeImageArtifacts(rawMessage?.artifacts);
  const toolActivity = normalizeToolActivity(rawMessage?.toolActivity);
  const generation = normalizeGenerationRequest(rawMessage?.metadata?.generation);
  const selectedTextContext = normalizeSelectedTextContext(rawMessage?.metadata?.selectedTextContext || rawMessage?.selectedTextContext);
  const runTrace = normalizeRunTrace(rawMessage?.runTrace);
  const workTrace = normalizeWorkTrace(rawMessage?.workTrace);
  if (role === "divider") {
    return {
      role,
      text,
      markerType: normalizeText(rawMessage?.metadata?.type),
      focus: normalizeText(rawMessage?.metadata?.focus),
      warning: normalizeText(rawMessage?.metadata?.warning)
    };
  }
  if (!text && role === "assistant" && !artifacts.length && !toolActivity.length && !runTrace && !workTrace) return null;
  return {
    role,
    text,
    error: Boolean(rawMessage?.error),
    generation,
    selectedTextContext,
    attachments,
    artifacts,
    sources: rawMessage?.sources,
    toolActivity,
    runTrace,
    workTrace
  };
}

function normalizeApiChatMessages(rawMessages) {
  return (Array.isArray(rawMessages) ? rawMessages : [])
    .map(normalizeApiChatMessage)
    .filter(Boolean);
}

function normalizeContextStatus(payload) {
  const raw = payload?.context && typeof payload.context === "object" ? payload.context : (payload || {});
  const contextLength = Math.max(0, Math.round(Number(raw.contextLength || raw.contextWindow) || 0));
  const tokensUsed = Math.max(0, Math.round(Number(
    raw.tokensUsed
    || raw.estimatedTokens
    || raw.requestTokens
    || raw.estimatedRequestTokens
  ) || 0));
  const estimatedRequestTokens = Math.max(0, Math.round(Number(raw.estimatedRequestTokens || tokensUsed) || 0));
  const percentFullRaw = raw.percentFull ?? (contextLength ? Math.round((tokensUsed / contextLength) * 100) : 0);
  const thresholdTokens = Math.max(0, Math.round(Number(raw.thresholdTokens || raw.compactionTriggerTokens) || 0));
  const thresholdPercentRaw = raw.thresholdPercent ?? (contextLength && thresholdTokens ? Math.round((thresholdTokens / contextLength) * 100) : 0);
  const compressionCount = Math.max(0, Math.round(Number(raw.compressionCount) || 0));
  return {
    sessionId: normalizeText(raw.sessionId),
    provider: normalizeProviderName(raw.provider) || currentReaderProvider(),
    model: normalizeText(raw.model) || currentReaderModel(),
    contextLength,
    tokensUsed,
    estimatedRequestTokens,
    actualInputTokens: Math.max(0, Math.round(Number(raw.actualInputTokens) || 0)),
    estimatedPercent: Math.min(100, Math.max(0, Math.round(Number(percentFullRaw) || 0))),
    actualUsageAvailable: Boolean(raw.actualUsageAvailable),
    usageUpdatedAt: normalizeText(raw.usageUpdatedAt),
    usageRequestId: normalizeText(raw.usageRequestId),
    messageTokens: Math.max(0, Math.round(Number(raw.messageTokens) || 0)),
    instructionTokens: Math.max(0, Math.round(Number(raw.instructionTokens) || 0)),
    toolSchemaTokens: Math.max(0, Math.round(Number(raw.toolSchemaTokens || raw.toolTokens) || 0)),
    thresholdTokens,
    percentFull: Math.min(100, Math.max(0, Math.round(Number(percentFullRaw) || 0))),
    thresholdPercent: Math.min(100, Math.max(0, Math.round(Number(thresholdPercentRaw) || 0))),
    messageCount: Math.max(0, Math.round(Number(raw.messageCount) || 0)),
    compactionEnabled: Boolean(raw.compactionEnabled),
    compactionReady: Boolean(raw.compactionReady),
    compressionCount,
    lastCompressedAt: normalizeText(raw.lastCompressedAt),
    summaryAvailable: Boolean(raw.summaryAvailable ?? compressionCount),
    lastCompressionError: normalizeText(raw.lastCompressionError),
    fallbackUsed: Boolean(raw.fallbackUsed)
  };
}

function formatTokenCount(value) {
  const count = Math.max(0, Math.round(Number(value) || 0));
  if (count >= 1_000_000) {
    const rounded = count / 1_000_000;
    return `${rounded >= 10 ? Math.round(rounded) : rounded.toFixed(1)}m`;
  }
  if (count >= 1000) {
    const rounded = count / 1000;
    return `${rounded >= 10 ? Math.round(rounded) : rounded.toFixed(1)}k`;
  }
  return String(count);
}

function hasAssistantResponseAfterLatestUser(messages, { normalizeMessage = null } = {}) {
  const normalizedMessages = Array.isArray(messages) ? messages : [];
  const lastUserIndex = normalizedMessages.reduce((latest, message, index) => (
    message?.role === "user" ? index : latest
  ), -1);
  return normalizedMessages.slice(Math.max(0, lastUserIndex + 1)).some((message) => {
    const normalized = typeof normalizeMessage === "function" ? normalizeMessage(message) : message;
    return normalized?.role === "assistant" && normalizeApiChatMessageText(normalized) && !normalized.error;
  });
}
