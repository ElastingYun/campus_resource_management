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
  reviewLabel?: string;
  integrationLabel?: string;
  effective?: boolean;
  stepLabel?: string;
  version?: number;
}
export interface ApplicationDraft {
  roomId: string;
  purpose: string;
  startsAt: string;
  endsAt: string;
}
export type ReviewAction = "APPROVE" | "REJECT" | "REVOKE";
export interface ApplicationDetails extends ApplicationView {
  version: number;
  allowedActions: ReviewAction[];
  history: {
    id: string;
    decision: string;
    actorId: string;
    comment: string;
    occurredAt: string;
  }[];
}
export interface WorkspaceQuery {
  offset?: number;
  limit?: number;
  review?: boolean;
}
export interface WorkspaceData {
  rooms: RoomOption[];
  applications: ApplicationView[];
  canSubmit?: boolean;
  canReview?: boolean;
  roomWarning?: string;
  pagination?: { offset: number; limit: number; hasNext: boolean };
}
export interface M2Gateway {
  readonly mode: "prototype" | "unconfigured" | "live";
  load(query?: WorkspaceQuery): Promise<WorkspaceData>;
  submit(draft: ApplicationDraft): Promise<ApplicationView>;
  detail?(id: string): Promise<ApplicationDetails>;
  decide?(
    id: string,
    action: "APPROVE" | "REJECT",
    comment: string,
    version: number,
  ): Promise<ApplicationView>;
  revoke?(id: string, version: number): Promise<ApplicationView>;
  pending?(): { label: string } | undefined;
  recover?(): Promise<ApplicationView>;
  simulateDecision?(
    id: string,
    decision: "accept" | "return",
  ): Promise<ApplicationView>;
}
export class GatewayMessage extends Error {}
