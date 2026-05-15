"use client";

import {
  AssistantRuntimeProvider,
  SimpleImageAttachmentAdapter,
  SimpleTextAttachmentAdapter,
  CompositeAttachmentAdapter,
  type AttachmentAdapter,
  type PendingAttachment,
  type CompleteAttachment,
} from "@assistant-ui/react";
import { useLangGraphRuntime } from "@assistant-ui/react-langgraph";
import { useRef } from "react";

import { createThread, sendMessage } from "@/lib/chatApi";
import { Thread } from "@/components/assistant-ui/thread";

class PDFAttachmentAdapter implements AttachmentAdapter {
  accept = "application/pdf,.pdf";

  async add(state: { file: File }): Promise<PendingAttachment> {
    return {
      id: state.file.name,
      type: "document" as const,
      name: state.file.name,
      contentType: state.file.type,
      file: state.file,
      status: { type: "requires-action" as const, reason: "composer-send" as const },
    };
  }

  async send(attachment: PendingAttachment): Promise<CompleteAttachment> {
    return {
      ...attachment,
      status: { type: "complete" as const },
      content: [
        {
          type: "text",
          text: attachment.name,
        },
      ],
    };
  }

  async remove() {}
}

const attachmentAdapter = new CompositeAttachmentAdapter([
  new SimpleImageAttachmentAdapter(),
  new SimpleTextAttachmentAdapter(),
  new PDFAttachmentAdapter(),
]);

export function Assistant() {
  const threadIdRef = useRef<string | null>(null);

  const runtime = useLangGraphRuntime({
    adapters: {
      attachments: attachmentAdapter,
    },
    stream: async function* (messages, { command }) {
      if (!threadIdRef.current) {
        const { thread_id } = await createThread();
        threadIdRef.current = thread_id;
      }
      const generator = await sendMessage({
        threadId: threadIdRef.current,
        messages: messages.slice(-1),
        command,
      });

      for await (const event of generator) {
        const e = event.event as string;
        if (e !== "messages/partial") continue;
        yield event;
      }
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex h-dvh">
        <div className="flex-1 min-h-0">
          <Thread />
        </div>
      </div>
    </AssistantRuntimeProvider>
  );
}
