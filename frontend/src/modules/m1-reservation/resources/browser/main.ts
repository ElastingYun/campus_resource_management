import { createApp } from "vue";
import BrowserFixture from "./BrowserFixture.vue";

// A test entry only. The normal App never imports or enables this fixture.
if (
  import.meta.env.VITE_B_RESOURCE_BROWSER_ACCEPTANCE !== "1" ||
  window.location.hostname !== "127.0.0.1"
) {
  throw new Error(
    "B browser fixture requires the explicit isolated loopback launcher",
  );
}
createApp(BrowserFixture).mount("#b-browser-fixture");
