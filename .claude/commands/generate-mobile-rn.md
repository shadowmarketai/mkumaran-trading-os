# Generate React Native Mobile App

Generate a React Native + Expo mobile app from the existing project's backend API.

## Instructions

1. **Analyze Backend API**
   - Read the backend routers, schemas, and models
   - Map all API endpoints, request/response types
   - Identify auth flow (JWT + Google OAuth)

2. **Initialize Expo Project**
   ```bash
   npx create-expo-app mobile --template expo-template-blank-typescript
   ```

3. **Install Dependencies**
   - expo-router (navigation)
   - @tanstack/react-query (API state)
   - zustand (client state)
   - expo-secure-store (token storage)
   - nativewind (styling) or react-native-paper (UI kit)
   - react-native-reanimated (animations)

4. **Generate Shared Types**
   - Extract TypeScript interfaces from backend schemas
   - Place in `mobile/types/` matching web frontend types

5. **Build Core Infrastructure**
   - API client with auth interceptor
   - Auth hook with secure token storage
   - Root layout with auth guard
   - Tab navigation layout

6. **Generate Screens** (parallel where possible)
   - Auth screens (login, register, forgot password)
   - Home/dashboard screen
   - Profile screen
   - Settings screen
   - Feature-specific screens based on PRP

7. **Configure for Production**
   - app.json with proper bundle ID, version, permissions
   - EAS Build configuration (eas.json)
   - App icons and splash screen
   - Environment variables

## Arguments

$ARGUMENTS can be:
- `scaffold` — Project setup + navigation only (no screens)
- `full` — Complete app generation (default)
- `screens-only` — Generate screens for existing project
- `auth-only` — Auth flow only

## Output

Report generated files and next steps:
```
MOBILE APP (React Native): [GENERATED]

Files created: [count]
Screens: [list]
API endpoints connected: [count]

Next steps:
1. cd mobile && npx expo start
2. Configure app.json for your bundle ID
3. Set EXPO_PUBLIC_API_URL in .env
4. Run /mobile-review for quality check
```
