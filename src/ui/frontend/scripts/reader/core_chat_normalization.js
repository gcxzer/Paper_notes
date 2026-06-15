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
  const contextLength = Math.max(0, Math.round(Number(raw.contextLength || raw.contextWindow || raw.context_length || raw.context_window) || 0));
  const tokensUsed = Math.max(0, Math.round(Number(
    raw.tokensUsed
    || raw.estimatedTokens
    || raw.requestTokens
    || raw.estimatedRequestTokens
    || raw.tokens_used
    || raw.estimated_tokens
  ) || 0));
  const estimatedRequestTokens = Math.max(0, Math.round(Number(raw.estimatedRequestTokens || raw.estimated_request_tokens || tokensUsed) || 0));
  const percentFullRaw = raw.percentFull ?? raw.percent_full ?? (contextLength ? Math.round((tokensUsed / contextLength) * 100) : 0);
  const thresholdTokens = Math.max(0, Math.round(Number(raw.thresholdTokens || raw.compactionTriggerTokens || raw.threshold_tokens || raw.compaction_trigger_tokens) || 0));
  const thresholdPercentRaw = raw.thresholdPercent ?? raw.threshold_percent ?? (contextLength && thresholdTokens ? Math.round((thresholdTokens / contextLength) * 100) : 0);
  const compressionCount = Math.max(0, Math.round(Number(raw.compressionCount || raw.compression_count) || 0));
  return {
    sessionId: normalizeText(raw.sessionId || raw.session_id),
    provider: normalizeProviderName(raw.provider) || currentReaderProvider(),
    model: normalizeText(raw.model) || currentReaderModel(),
    contextLength,
    tokensUsed,
    estimatedRequestTokens,
    actualInputTokens: Math.max(0, Math.round(Number(raw.actualInputTokens || raw.actual_input_tokens) || 0)),
    estimatedPercent: Math.min(100, Math.max(0, Math.round(Number(percentFullRaw) || 0))),
    actualUsageAvailable: Boolean(raw.actualUsageAvailable ?? raw.actual_usage_available),
    usageUpdatedAt: normalizeText(raw.usageUpdatedAt || raw.usage_updated_at),
    usageRequestId: normalizeText(raw.usageRequestId || raw.usage_request_id),
    messageTokens: Math.max(0, Math.round(Number(raw.messageTokens || raw.message_tokens) || 0)),
    instructionTokens: Math.max(0, Math.round(Number(raw.instructionTokens || raw.instruction_tokens) || 0)),
    toolSchemaTokens: Math.max(0, Math.round(Number(raw.toolSchemaTokens || raw.toolTokens || raw.tool_schema_tokens || raw.tool_tokens) || 0)),
    thresholdTokens,
    percentFull: Math.min(100, Math.max(0, Math.round(Number(percentFullRaw) || 0))),
    thresholdPercent: Math.min(100, Math.max(0, Math.round(Number(thresholdPercentRaw) || 0))),
    messageCount: Math.max(0, Math.round(Number(raw.messageCount || raw.message_count) || 0)),
    compactionEnabled: Boolean(raw.compactionEnabled ?? raw.compaction_enabled),
    compactionReady: Boolean(raw.compactionReady ?? raw.compaction_ready),
    compressionCount,
    lastCompressedAt: normalizeText(raw.lastCompressedAt || raw.last_compressed_at),
    summaryAvailable: Boolean(raw.summaryAvailable ?? raw.summary_available ?? compressionCount),
    lastCompressionError: normalizeText(raw.lastCompressionError || raw.last_compression_error),
    fallbackUsed: Boolean(raw.fallbackUsed ?? raw.fallback_used)
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
