import { describe, expect, it, vi } from "vitest";
import { createHttpResourceGateway } from "./gateway";
import { createPrototypeResourceGateway } from "./prototype";

const example = async () =>
  (await createPrototypeResourceGateway().listRooms({})).items[0]!;

describe("resource HTTP adapter", () => {
  it("reads validated JSON with same-origin credentials and no redirects", async () => {
    const room = await example();
    const request = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        Response.json({ items: [room], total: 1, limit: 20, offset: 0 }),
      );
    const result = await createHttpResourceGateway(request).listRooms({
      q: "A 101",
    });
    expect(result.items[0]?.id).toBe("1");
    expect(request.mock.calls[0]?.[0]).toBe("/api/v1/resources/rooms?q=A+101");
    expect(request.mock.calls[0]?.[1]).toMatchObject({
      credentials: "same-origin",
      mode: "same-origin",
      redirect: "error",
      method: "GET",
    });
  });
  it("carries the revision and stable identifier when editing", async () => {
    const room = await example();
    const request = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(room));
    await createHttpResourceGateway(request).updateRoom(
      room.id,
      { code: room.code, name: room.name, location: room.location },
      room.revision,
    );
    expect(
      JSON.parse(String(request.mock.calls[0]?.[1]?.body)).expected_revision,
    ).toBe(room.revision);
    expect(request.mock.calls[0]?.[1]?.method).toBe("PATCH");
  });
  it.each([
    [403, false],
    [409, false],
    [422, false],
    [503, true],
    [408, true],
  ])(
    "distinguishes rejected and uncertain writes for HTTP %i",
    async (status, uncertain) => {
      const request = vi
        .fn<typeof fetch>()
        .mockResolvedValue(
          new Response("private-server-error", { status: Number(status) }),
        );
      const result = createHttpResourceGateway(request).createRoom({
        code: "A",
        name: "A",
        location: "A",
      });
      await expect(result).rejects.toMatchObject({ uncertain, status });
      await expect(result).rejects.not.toHaveProperty(
        "message",
        "private-server-error",
      );
      expect(request).toHaveBeenCalledTimes(1);
    },
  );
  it("does not equate a network failure with a rejected write", async () => {
    const request = vi
      .fn<typeof fetch>()
      .mockRejectedValue(new TypeError("network"));
    const gateway = createHttpResourceGateway(request);
    await expect(
      gateway.createSeat("1", { code: "01", outlet_type: "none" }),
    ).rejects.toMatchObject({ uncertain: true });
    await expect(gateway.listRooms({})).rejects.toMatchObject({
      uncertain: false,
    });
  });
  it("marks malformed write success as unknown, never fabricated success", async () => {
    const request = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json({ id: "fake" }));
    await expect(
      createHttpResourceGateway(request).createRoom({
        code: "A",
        name: "A",
        location: "A",
      }),
    ).rejects.toMatchObject({ uncertain: true });
  });
  it("rejects numeric BIGINT IDs instead of losing precision", async () => {
    const room = { ...(await example()), id: 9007199254740993 };
    const request = vi
      .fn<typeof fetch>()
      .mockResolvedValue(
        Response.json({ items: [room], total: 1, limit: 20, offset: 0 }),
      );
    await expect(
      createHttpResourceGateway(request).listRooms({}),
    ).rejects.toMatchObject({ uncertain: false });
  });
  it("rejects a seat list belonging to another room", async () => {
    const gateway = createPrototypeResourceGateway();
    const data = await gateway.listSeats("2", {});
    const request = vi
      .fn<typeof fetch>()
      .mockResolvedValue(Response.json(data));
    await expect(
      createHttpResourceGateway(request).listSeats("1", {}),
    ).rejects.toMatchObject({ uncertain: false });
  });
  it("does not send invalid base URLs, identifiers or pre-aborted reads", async () => {
    const request = vi.fn<typeof fetch>();
    await expect(
      createHttpResourceGateway(request, "https://untrusted.example").listRooms(
        {},
      ),
    ).rejects.toMatchObject({ uncertain: false });
    expect(() =>
      createHttpResourceGateway(request).updateSeat(
        "../other",
        { code: "1", outlet_type: "none" },
        "0".repeat(64),
      ),
    ).toThrow();
    await expect(
      createHttpResourceGateway(request).listRooms({}, AbortSignal.abort()),
    ).rejects.toMatchObject({ uncertain: false });
    expect(request).not.toHaveBeenCalled();
  });
});
