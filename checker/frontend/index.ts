import { registerRootComponent } from "expo";

import App from "./src/App";

// Expo's default page reset assumes a ScrollView; this app scrolls the page itself.
document.getElementById("expo-reset")?.remove();
const reset = document.createElement("style");
reset.textContent = "html,body{min-height:100%;margin:0} #root{display:flex;flex-direction:column;min-height:100vh}";
document.head.appendChild(reset);

registerRootComponent(App);
