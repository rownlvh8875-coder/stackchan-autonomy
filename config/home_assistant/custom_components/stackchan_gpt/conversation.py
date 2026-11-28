"""Answers for Assist from the local, budgeted StackChan service."""

from aiohttp import ClientError, ClientTimeout
from homeassistant.components import conversation
from homeassistant.helpers import intent
from homeassistant.helpers.aiohttp_client import async_get_clientsession

ANSWER_URL = "http://127.0.0.1:10301/answer"
SERVICE_UNAVAILABLE = "지금은 답변할 수 없어요."
BUDGET_EXHAUSTED = "지금은 대화 사용량 한도에 도달했어요."


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([StackChanConversation(async_get_clientsession(hass), entry.entry_id)])


class StackChanConversation(conversation.ConversationEntity):
    _attr_name = "StackChan GPT"

    def __init__(self, session, entry_id):
        self._session = session
        self._attr_unique_id = entry_id

    @property
    def supported_languages(self) -> list[str]:
        return ["ko", "ko-KR"]

    async def _async_handle_message(self, user_input, chat_log):
        try:
            async with self._session.post(
                ANSWER_URL,
                json={"text": user_input.text},
                allow_redirects=False,
                timeout=ClientTimeout(total=25),
            ) as reply:
                if reply.status == 429:
                    return self._error(user_input, chat_log, BUDGET_EXHAUSTED)
                if reply.status != 200:
                    return self._error(user_input, chat_log, SERVICE_UNAVAILABLE)
                payload = await reply.json()
        except (ClientError, TimeoutError, ValueError):
            return self._error(user_input, chat_log, SERVICE_UNAVAILABLE)

        answer = payload.get("answer") if isinstance(payload, dict) else None
        if not isinstance(answer, str) or len(answer) > 800 or not answer.strip():
            return self._error(user_input, chat_log, SERVICE_UNAVAILABLE)
        chat_log.async_add_assistant_content_without_tools(
            conversation.AssistantContent(agent_id=self.entity_id, content=answer)
        )
        result = conversation.async_get_result_from_chat_log(user_input, chat_log)
        result.continue_conversation = False
        return result

    def _error(self, user_input, chat_log, message):
        response = intent.IntentResponse(language=user_input.language)
        response.async_set_error(intent.IntentResponseErrorCode.FAILED_TO_HANDLE, message)
        return conversation.ConversationResult(
            response=response, conversation_id=chat_log.conversation_id, continue_conversation=False
        )
