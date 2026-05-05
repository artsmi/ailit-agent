# Design Document: AI Agent Interface (Candy Style)

## Project Overview
A vibrant, high-fidelity web interface for an AI Agent system featuring a central chat workspace and an agent interaction graph. The design uses the "Candy" design system, characterized by playful shapes, bold colors, and soft typography.

## Brand Identity & Visual Language
- **Style:** "Joyful Pop" — Energetic, clean, and modern.
- **Core Shape:** Pill-shaped (Full Roundness) for buttons, inputs, and badges.
- **Color Palette:**
  - Primary: `#e040a0` (Vibrant Pink/Magenta)
  - Surface: White with soft shadows.
  - Background: Pale grey-blue.
- **Typography:** `DM Sans` (Clean, rounded sans-serif).

## Core Layout Components

### 1. Left Navigation Bar (Sidebar)
- **Width:** 260px (approx).
- **Style:** Clean white background, border-right.
- **Elements:**
  - **Logo:** "AI Ко-пилот" in bold black.
  - **Primary CTA:** "НОВЫЙ ДИАЛОГ" (New Dialog) — Pill-shaped button, primary color background, white text, leading '+' icon.
  - **Navigation Links:** "Новый чат" (New Chat), "История" (History), "Агенты" (Agents).
  - **Active State:** Light pink background with primary color icon and text.

### 2. Header (Top Bar)
- **Title:** Page title (e.g., "Технический воркфлоу") and file breadcrumb.
- **Trailing Actions:** Analytics Toggle, Settings (Gear icon), More (Vertical dots).
- **Style:** Thin border-bottom, subtle spacing.

### 3. Main Chat Workspace (SCREEN_3)
- **Max Width:** 800px (Centered).
- **Message Format:**
  - **User:** Grey icon/label, simple text.
  - **Agent:** Robot icon, primary color accent.
  - **Content:** Strict Markdown (clean text, no heavy styling).
- **Console Output Block:**
  - **Header:** "CONSOLE OUTPUT" in small bold caps.
  - **Behavior:** Limit to 5 lines by default.
  - **Expansion:** "ПОКАЗАТЬ ПОЛНОСТЬЮ" (Show Full) link with chevron.
- **Input Area:**
  - Centered pill-shaped container.
  - Placeholder: "Ответьте или введите новую команду..."
  - Floating action: Large pink pill-shaped "Send" button with upward arrow.

### 4. Agent Interaction Graph (SCREEN_14)
- **Nodes:** Large rounded white boxes with central icons (Magnifier, Gear, Code, Checkmark).
- **Labels:** Pill-shaped badges under nodes (SUPERVISOR, RESEARCHER, CODER, REVIEWER).
- **Active State:** Pink glow/shadow around the active agent (e.g., CODER ACTIVE).
- **Links:** Directed arrows. Active data flow represented by pink dashed lines.
- **Controls:** Floating bottom pill with Play/Pause and Zoom controls.

### 5. Analytics Panel (Right Sidebar)
- **Visibility:** Hidden by default.
- **Content:** Context details, project ID, token usage progress bar, model version.
- **Style:** Slide-out panel from the right.

## Technical Implementation Notes (CSS/Tokens)
- **Border Radius:** `border-radius: 9999px` (Full pill).
- **Shadows:** `box-shadow: 0 4px 12px rgba(224, 64, 160, 0.15)` for active agents.
- **Spacing:** Relaxed, generous whitespace to maintain "Candy" feel.
