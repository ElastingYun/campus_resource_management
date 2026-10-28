import { GatewayMessage } from "./models";
import type {
  ApplicationDraft,
  ApplicationView,
  M2Gateway,
  WorkspaceData,
} from "./models";

export function createUnconfiguredGateway(): M2Gateway {
  const unavailable = async (): Promise<never> => {
    throw new GatewayMessage(
      "申请服务尚未接入，暂时无法读取或提交。可以先查看交互原型。",
    );
  };
  return { mode: "unconfigured", load: unavailable, submit: unavailable };
}

/** Synthetic data is used only on the explicitly labelled prototype route. */
export function createPrototypeGateway(): M2Gateway {
  const data: WorkspaceData = {
    rooms: [
      {
        id: "DEMO-ROOM-01",
        name: "示例研讨室 A",
        location: "示例教学楼 · 二层",
      },
      {
        id: "DEMO-ROOM-02",
        name: "示例研讨室 B",
        location: "示例教学楼 · 三层",
      },
    ],
    applications: [
      {
        id: "DEMO-001",
        roomId: "DEMO-ROOM-01",
        roomName: "示例研讨室 A",
        purpose: "课程小组讨论（示例）",
        startsAt: "2026-10-29T09:00",
        endsAt: "2026-10-29T11:00",
        statusLabel: "示例待处理",
        statusTone: "neutral",
        note: "此记录仅用于交互演示。审批流程和正式状态待团队确认。",
      },
      {
        id: "DEMO-002",
        roomId: "DEMO-ROOM-02",
        roomName: "示例研讨室 B",
        purpose: "课堂展示排练（示例）",
        startsAt: "2026-10-30T14:00",
        endsAt: "2026-10-30T16:00",
        statusLabel: "示例已处理",
        statusTone: "positive",
        note: "示例展示不代表真实审批或座位占用生效。",
      },
      {
        id: "DEMO-003",
        roomId: "DEMO-ROOM-01",
        roomName: "示例研讨室 A",
        purpose: "补充申请资料（示例）",
        startsAt: "2026-10-31T10:00",
        endsAt: "2026-10-31T12:00",
        statusLabel: "示例需补充",
        statusTone: "attention",
        note: "这是一条供讨论的反馈示例，不定义实际业务规则。",
      },
    ],
  };
  let sequence = 3;
  const copy = <T>(value: T): T => structuredClone(value);
  return {
    mode: "prototype",
    async load() {
      return copy(data);
    },
    async submit(draft: ApplicationDraft) {
      const room = data.rooms.find((item) => item.id === draft.roomId);
      if (!room) throw new GatewayMessage("请选择当前列表中的示例教室。");
      const record: ApplicationView = {
        ...draft,
        id: `DEMO-${String(++sequence).padStart(3, "0")}`,
        roomName: room.name,
        statusLabel: "示例待处理",
        statusTone: "neutral",
        note: "仅保存在本页演示中；未发送真实申请，刷新后重置。",
      };
      data.applications.unshift(record);
      return copy(record);
    },
    async simulateDecision(id, decision) {
      const record = data.applications.find((item) => item.id === id);
      if (!record) throw new GatewayMessage("示例记录不存在，请重新载入。");
      record.statusLabel = decision === "accept" ? "示例已处理" : "示例需补充";
      record.statusTone = decision === "accept" ? "positive" : "attention";
      record.note = "仅演示本页状态变化，没有进行真实审批或改变座位占用。";
      return copy(record);
    },
  };
}
