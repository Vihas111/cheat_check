import "react-native";

// react-native-web reports hover and focus on pressables; React Native's own types leave them out.
declare module "react-native" {
  interface PressableStateCallbackType {
    hovered?: boolean;
    focused?: boolean;
  }
}
