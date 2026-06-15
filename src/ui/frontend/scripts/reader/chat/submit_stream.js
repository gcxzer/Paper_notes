async function submitReaderChatStream(body, {
  signal,
  getSessionRunKey = () => chatSessionRunKey(body?.sessionId),
  onStart = null
} = {}) {
  let finalPayload = null;
  let streamStarted = false;
  let streamError = null;
  try {
    await fetchAgentEventStream("/api/chat/stream", {
      body,
      signal,
      onEvent: ({ event, data }) => {
        streamStarted = true;
        if (event === "start" && typeof onStart === "function") onStart(data || {});
        const sessionRunKey = getSessionRunKey();
        if (readerState.chatProgressRequestIdsBySession[sessionRunKey] !== body.requestId) return;
        if (data?.progress) {
          setReaderChatProgress(data.progress, sessionRunKey);
        }
        if (event === "work_trace_item" || event === "work_trace_delta") {
          appendReaderChatProgressWorkTrace(data, sessionRunKey, event);
        }
        if (event === "model_delta") {
          if (isCurrentChatSessionRunKey(sessionRunKey)) appendReaderStreamingDelta(data?.delta);
        } else if (event === "final") {
          finalPayload = data;
        } else if (event === "error") {
          streamError = new AgentRequestError(
            normalizeText(data?.error) || GENERIC_AGENT_ERROR,
            { code: normalizeText(data?.code), payload: data }
          );
          streamError.streamStarted = streamStarted;
        }
      }
    });
  } catch (error) {
    if (!finalPayload) throw error;
    console.debug("Chat stream ended after final payload with a recoverable close error.", error);
  }
  if (finalPayload) return finalPayload;
  if (streamError) throw streamError;
  const error = new AgentRequestError("Chat stream ended before a final response.", { code: "stream_incomplete" });
  error.streamStarted = streamStarted;
  throw error;
}

function hasSuccessfulAssistantAfterLatestReaderUser(messages = readerState.chatMessages) {
  return hasAssistantResponseAfterLatestUser(messages, { normalizeMessage: normalizeChatMessage });
}
