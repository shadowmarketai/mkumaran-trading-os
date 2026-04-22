# Generate Flutter Mobile App

Generate a Flutter mobile app from the existing project's backend API using clean architecture.

## Instructions

1. **Analyze Backend API**
   - Read the backend routers, schemas, and models
   - Map all API endpoints, request/response types
   - Identify auth flow (JWT + Google OAuth)

2. **Initialize Flutter Project**
   ```bash
   flutter create --org com.yourcompany --project-name app_name mobile_flutter
   ```

3. **Install Dependencies** (pubspec.yaml)
   - flutter_riverpod or flutter_bloc (state management)
   - go_router (navigation)
   - dio (HTTP client)
   - flutter_secure_storage (token storage)
   - freezed + json_serializable (code generation)
   - fpdart (functional error handling)
   - flutter_test + mockito (testing)

4. **Set Up Architecture**
   - Create feature-first folder structure
   - Set up core/ with network client, error types, storage
   - Configure analysis_options.yaml with strict rules
   - Create app router with auth redirect

5. **Generate Domain Layer** (per feature)
   - Entities from backend models
   - Repository interfaces
   - Use cases

6. **Generate Data Layer** (per feature)
   - DTOs with JSON serialization
   - Repository implementations
   - Remote data sources with Dio

7. **Generate Presentation Layer** (per feature)
   - State classes (sealed types)
   - State notifiers/blocs
   - Screen widgets
   - Reusable components

8. **Configure for Production**
   - App icons (flutter_launcher_icons)
   - Splash screen (flutter_native_splash)
   - Flavors for dev/staging/prod
   - Fastlane configuration

## Arguments

$ARGUMENTS can be:
- `scaffold` — Project setup + architecture only
- `full` — Complete app generation (default)
- `feature [name]` — Generate a single feature module
- `auth-only` — Auth feature only

## Output

Report generated files and next steps:
```
MOBILE APP (Flutter): [GENERATED]

Files created: [count]
Features: [list]
API endpoints connected: [count]

Next steps:
1. cd mobile_flutter && flutter run
2. Update lib/core/constants.dart with API_URL
3. Run flutter analyze
4. Run /mobile-review for quality check
```
