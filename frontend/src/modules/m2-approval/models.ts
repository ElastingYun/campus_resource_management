/** Page view models, not an approved backend request/response contract. */
export interface RoomOption {
  id: string;
  name: string;
  location: string;
}
export interface ApplicationView {
  id: string;
  roomId: string;
  roomName: string;
  purpose: string;
  startsAt: string;
  endsAt: string;
  statusLabel: string;
  statusTone: "neutral" | "positive" | "attention";
  note: string;
}
export interface ApplicationDraft {
  roomId: string;
  purpose: string;
  startsAt: string;
  endsAt: string;
}
export interface WorkspaceData {
  rooms: RoomOption[];
  applications: ApplicationView[];
}
export interface M2Gateway {
  readonly mode: "prototype" | "unconfigured" | "live";
  load(): Promise<WorkspaceData>;
  submit(draft: ApplicationDraft): Promise<ApplicationView>;
  simulateDecision?(
    id: string,
    decision: "accept" | "return",
  ): Promise<ApplicationView>;
}
export class GatewayMessage extends Error {}
