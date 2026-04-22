# Mobile Code Review

Run a comprehensive mobile code review for React Native and/or Flutter projects.

## Instructions

Detect which mobile frameworks are present and review accordingly.

### React Native Review

If `mobile/` or React Native project exists:

1. **TypeScript Strictness** — No `any` types, proper generics, strict null checks
2. **Navigation** — Proper auth guards, deep link handling, back navigation
3. **State Management** — No prop drilling, proper cache invalidation, optimistic updates
4. **Performance** — FlashList over FlatList, memoized renders, image optimization
5. **Security** — Tokens in SecureStore, no secrets in code, certificate pinning
6. **Accessibility** — accessibilityLabel on all touchables, min 44pt targets
7. **Platform Handling** — Platform.select usage, safe area handling
8. **Testing** — Component tests, hook tests, snapshot tests

### Flutter Review

If `mobile_flutter/` or Flutter project exists:

1. **Architecture** — Clean architecture boundaries, no Flutter imports in domain
2. **State Management** — Sealed state classes, no boolean soup, proper disposal
3. **Widget Quality** — const constructors, build() under 80 lines, proper keys in lists
4. **Dart Idioms** — final over var, no bang operator abuse, pattern matching
5. **Performance** — ListView.builder for lists, no expensive work in build()
6. **Security** — Tokens in secure storage, no hardcoded secrets, HTTPS only
7. **Accessibility** — Semantic labels, 48px touch targets, color contrast
8. **Testing** — Unit tests for logic, widget tests for UI, golden tests for design

### Both Platforms

1. **API Integration** — Proper error handling, retry logic, offline support
2. **Auth Flow** — Secure token storage, refresh token handling, biometric option
3. **Deep Links** — URL validation, auth guards on deep link routes
4. **Push Notifications** — Proper permission handling, token management
5. **App Store Readiness** — Icons, splash, permissions, privacy policy

## Output

```
MOBILE REVIEW: [PASS/FAIL]

React Native:
  TypeScript:     [OK/X issues]
  Navigation:     [OK/X issues]
  Security:       [OK/X issues]
  Performance:    [OK/X issues]
  Accessibility:  [OK/X issues]
  Tests:          [X/Y passed]

Flutter:
  Architecture:   [OK/X issues]
  State Mgmt:     [OK/X issues]
  Security:       [OK/X issues]
  Performance:    [OK/X issues]
  Accessibility:  [OK/X issues]
  Tests:          [X/Y passed]

Critical Issues: [count]
Ready for app store: [YES/NO]
```

## Arguments

$ARGUMENTS can be:
- `rn` — React Native only
- `flutter` — Flutter only
- `both` — Both platforms (default)
- `security` — Security-focused review only
