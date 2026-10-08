import { View } from "react-native";

import { MetaProvider } from "./meta";
import { RouterProvider, useRouter } from "./router";
import { AssignmentScreen } from "./screens/Assignment";
import { ItemScreen } from "./screens/Item";
import { CompareScreen } from "./screens/Compare";
import { GraderScreen } from "./screens/Grader";
import { Home, NewAssignment } from "./screens/Home";
import { CalibrateScreen, GroupsScreen } from "./screens/Insights";
import { SettingsScreen } from "./screens/Settings";
import { SetupScreen } from "./screens/Setup";
import { ThemeProvider } from "./theme";
import { AppBar, FeedbackProvider, Page } from "./ui/chrome";
import { Button, Reveal, T } from "./ui/primitives";

function Missing() {
  const { navigate } = useRouter();
  return (
    <Page bar={<AppBar title="Not found" />} narrow>
      <T>There is nothing at this address.</T>
      <View style={{ flexDirection: "row" }}><Button variant="primary" label="Back to assignments" onPress={() => navigate("/")} /></View>
    </Page>
  );
}

function Screen() {
  const { route } = useRouter();
  const p = route.params;
  switch (route.name) {
    case "home": return <Home />;
    case "new": return <NewAssignment />;
    case "settings": return <SettingsScreen />;
    case "assignment": return <AssignmentScreen key={p.aid} aid={p.aid} />;
    case "setup": return <SetupScreen key={p.aid} aid={p.aid} />;
    case "clusters": return <GroupsScreen key={p.aid} aid={p.aid} />;
    case "calibrate": return <CalibrateScreen key={p.aid} aid={p.aid} />;
    case "submission": return <GraderScreen key={p.sid} sid={p.sid} />;
    case "item": return <ItemScreen key={p.iid} iid={p.iid} />;
    case "compare": return <CompareScreen key={p.mid} mid={p.mid} />;
    default: return <Missing />;
  }
}

/** Each new address slides its screen in from the side it came from, so moving around feels physical. */
function Stage() {
  const { route, direction } = useRouter();
  return <Reveal key={route.path} x={direction * 28} y={0}><Screen /></Reveal>;
}

export default function App() {
  return (
    <ThemeProvider>
      <RouterProvider>
        <FeedbackProvider>
          <MetaProvider>
            <Stage />
          </MetaProvider>
        </FeedbackProvider>
      </RouterProvider>
    </ThemeProvider>
  );
}
