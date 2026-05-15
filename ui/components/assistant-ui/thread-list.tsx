"use client";

import {
  ThreadListItemPrimitive,
  ThreadListPrimitive,
} from "@assistant-ui/react";
import {
  PlusIcon,
  ArchiveIcon,
  Trash2Icon,
  ArchiveRestoreIcon,
} from "lucide-react";
import type { FC } from "react";

export const ThreadList: FC = () => {
  return (
    <div className="flex h-full flex-col border-r bg-muted/30">
      <ThreadListPrimitive.Root className="flex min-h-0 flex-1 flex-col">
        <ThreadListHeader />
        <div className="flex-1 overflow-y-auto">
          <ThreadListPrimitive.Items
            components={{ ThreadListItem }}
          />
          <ThreadListPrimitive.Items
            archived
            components={{ ThreadListItem: ArchivedThreadListItem }}
          />
        </div>
      </ThreadListPrimitive.Root>
    </div>
  );
};

const ThreadListHeader: FC = () => {
  return (
    <div className="flex items-center justify-between border-b px-4 py-3">
      <h2 className="font-semibold text-sm">Chats</h2>
      <ThreadListPrimitive.New asChild>
        <button className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
          <PlusIcon className="size-4" />
        </button>
      </ThreadListPrimitive.New>
    </div>
  );
};

const ThreadListItem: FC = () => {
  return (
    <ThreadListItemPrimitive.Root className="group flex items-center gap-2">
      <ThreadListItemPrimitive.Trigger className="flex-1 truncate rounded-md px-4 py-2 text-left text-sm transition-colors hover:bg-accent data-[current]:bg-accent">
        <ThreadListItemPrimitive.Title fallback={<span className="text-muted-foreground">New Chat</span>} />
      </ThreadListItemPrimitive.Trigger>
      <div className="flex shrink-0 gap-0.5 pr-2 opacity-0 transition-opacity group-hover:opacity-100">
        <ThreadListItemPrimitive.Archive asChild>
          <button className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
            <ArchiveIcon className="size-3.5" />
          </button>
        </ThreadListItemPrimitive.Archive>
        <ThreadListItemPrimitive.Delete asChild>
          <button className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive">
            <Trash2Icon className="size-3.5" />
          </button>
        </ThreadListItemPrimitive.Delete>
      </div>
    </ThreadListItemPrimitive.Root>
  );
};

const ArchivedThreadListItem: FC = () => {
  return (
    <ThreadListItemPrimitive.Root className="group flex items-center gap-2 opacity-60">
      <ThreadListItemPrimitive.Trigger className="flex-1 truncate rounded-md px-4 py-2 text-left text-sm transition-colors hover:bg-accent data-[current]:bg-accent">
        <ThreadListItemPrimitive.Title fallback={<span className="text-muted-foreground">New Chat</span>} />
      </ThreadListItemPrimitive.Trigger>
      <div className="flex shrink-0 gap-0.5 pr-2 opacity-0 transition-opacity group-hover:opacity-100">
        <ThreadListItemPrimitive.Unarchive asChild>
          <button className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground">
            <ArchiveRestoreIcon className="size-3.5" />
          </button>
        </ThreadListItemPrimitive.Unarchive>
        <ThreadListItemPrimitive.Delete asChild>
          <button className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive">
            <Trash2Icon className="size-3.5" />
          </button>
        </ThreadListItemPrimitive.Delete>
      </div>
    </ThreadListItemPrimitive.Root>
  );
};
