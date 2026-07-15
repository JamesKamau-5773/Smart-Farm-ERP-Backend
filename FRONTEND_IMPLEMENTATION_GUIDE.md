# Frontend Implementation Guide: Protein-Based Feed Formulation

## Overview
The backend now supports dynamic recipe formulation with protein targeting and automatic ingredient adjustment. This guide outlines what the frontend needs to implement.

---

## 1. Architecture Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    User Workflow                                │
└─────────────────────────────────────────────────────────────────┘

MILK LAB                           FEED FORMULATION
───────────────────────────────────────────────────────────────
1. User sets yield targets    →  2. Frontend requests suggested mix
2. System calculates herd plan →  3. Backend returns protein target
4. Backend saves yield_target_id

                                  5. User adjusts target protein %
                                  6. Frontend calls formulation API
                                  7. Backend suggests ingredient mix
                                  8. User reviews & saves recipe
                                  9. Frontend calls auto-save API
                                  10. Recipe marked as ADOPTED
```

---

## 2. Backend API Endpoints

### A. Recipe Formulation - Calculate Nutrition
**Purpose:** Get current protein % of a recipe before adjustment

```http
POST /api/v1/recipes/calculate-nutrition
Authorization: Bearer {JWT}
Content-Type: application/json

{
  "batch_size_kg": 500,
  "ingredients": [
    {"ingredient_id": 1, "percentage": 50},
    {"ingredient_id": 2, "percentage": 30},
    {"ingredient_id": 3, "percentage": 20}
  ]
}

RESPONSE 200 OK:
{
  "batch_size_kg": 500,
  "ingredients": [
    {
      "ingredient_id": 1,
      "percentage": 50,
      "weight_kg": 250,
      "protein_grams_per_kg": 120,
      "total_protein_grams": 30000
    },
    {
      "ingredient_id": 2,
      "percentage": 30,
      "weight_kg": 150,
      "protein_grams_per_kg": 80,
      "total_protein_grams": 12000
    },
    {
      "ingredient_id": 3,
      "percentage": 20,
      "weight_kg": 100,
      "protein_grams_per_kg": 200,
      "total_protein_grams": 20000
    }
  ],
  "total_protein_grams": 62000,
  "average_protein_percent": 12.4
}
```

### B. Recipe Formulation - Suggest Adjustments
**Purpose:** Get ingredient adjustments to hit target protein %

```http
POST /api/v1/recipes/formulate
Authorization: Bearer {JWT}
Content-Type: application/json

{
  "batch_size_kg": 500,
  "target_protein_percent": 16.5,
  "ingredients": [
    {"ingredient_id": 1, "percentage": 50},
    {"ingredient_id": 2, "percentage": 30},
    {"ingredient_id": 3, "percentage": 20}
  ],
  "yield_target_id": 123  // optional, for tracking
}

RESPONSE 200 OK:
{
  "current_protein_percent": 12.4,
  "target_protein_percent": 16.5,
  "adjustment_needed": 4.1,
  "adjusted_ingredients": [
    {
      "ingredient_id": 1,
      "name": "Maize Germ",
      "current_percentage": 50,
      "adjusted_percentage": 35,
      "adjustment": -15,
      "protein_grams_per_kg": 120
    },
    {
      "ingredient_id": 2,
      "name": "Wheat Bran",
      "current_percentage": 30,
      "adjusted_percentage": 25,
      "adjustment": -5,
      "protein_grams_per_kg": 80
    },
    {
      "ingredient_id": 3,
      "name": "Sunflower Cake",
      "current_percentage": 20,
      "adjusted_percentage": 40,
      "adjustment": +20,
      "protein_grams_per_kg": 200
    }
  ],
  "projected_nutrition": {
    "batch_size_kg": 500,
    "total_protein_grams": 82500,
    "average_protein_percent": 16.5,
    "ingredients": [...]
  },
  "adjustment_strategy": "Adjusted high/low protein ingredients to shift from 12.4% to 16.5% protein."
}
```

### C. Recipe Formulation - Auto-Save Recipe
**Purpose:** Save formulated recipe and mark as ADOPTED

```http
POST /api/v1/recipes/auto-save
Authorization: Bearer {JWT}
Content-Type: application/json

{
  "recipe_name": "Herd Target 4.3L - 16.5% Protein",
  "batch_size_kg": 500,
  "target_protein_percent": 16.5,
  "adjusted_ingredients": [
    {"ingredient_id": 1, "percentage": 35},
    {"ingredient_id": 2, "percentage": 25},
    {"ingredient_id": 3, "percentage": 40}
  ],
  "yield_target_id": 123  // optional
}

RESPONSE 201 CREATED:
{
  "recipe_id": 42,
  "recipe_name": "Herd Target 4.3L - 16.5% Protein",
  "target_protein_percent": 16.5,
  "achieved_protein_percent": 16.5,
  "batch_size_kg": 500,
  "status": "ADOPTED",
  "message": "Recipe 'Herd Target 4.3L - 16.5% Protein' has been formulated and adopted for the herd.",
  "nutrition_summary": {
    "batch_size_kg": 500,
    "total_protein_grams": 82500,
    "average_protein_percent": 16.5,
    "ingredients": [...]
  }
}
```

### D. Get Suggested Feed Mix (Milk Lab Integration)
**Purpose:** Get pre-calculated protein target and ingredient suggestions from Milk Lab

```http
GET /api/v1/feed-formulation/suggested-mix?batch_size_kg=500&yield_target_id=123
Authorization: Bearer {JWT}

RESPONSE 200 OK:
{
  "herd_total_target_liters": 4.3,
  "suggested_protein_percent": 16.5,
  "batch_size_kg": 500,
  "suggested_ingredients": [
    {
      "ingredient_id": 1,
      "name": "Maize Germ",
      "percentage": 0,
      "protein_grams_per_kg": 120
    },
    {
      "ingredient_id": 2,
      "name": "Wheat Bran",
      "percentage": 0,
      "protein_grams_per_kg": 80
    },
    {
      "ingredient_id": 3,
      "name": "Sunflower Cake",
      "percentage": 0,
      "protein_grams_per_kg": 200
    }
  ],
  "message": "Suggested feed mix based on Milk Lab yield targets."
}
```

---

## 3. Frontend Components Required

### 3.1 Nutrition Lab Page - Protein Input Section

**Component: ProteinTargetInput**
```jsx
<ProteinTargetInput 
  currentProteinPercent={12.4}
  targetProteinPercent={16.5}
  onTargetChange={(newTarget) => {
    // Call POST /api/v1/recipes/formulate
  }}
  batchSizeKg={500}
  onBatchSizeChange={(newSize) => {
    // Recalculate nutrition
  }}
/>
```

**Responsibilities:**
- Display current protein % vs target
- Show progress bar (green if met, orange if needs adjustment)
- Allow user to input target protein % (0-100 range)
- Show batch size input (default 500kg)
- Real-time updates as user changes values

**UI Elements:**
```
┌──────────────────────────────────┐
│ Protein Target Configuration      │
├──────────────────────────────────┤
│                                  │
│ Current Protein:  [12.4%]        │
│ Target Protein:   [________] %   │
│                                  │
│ Batch Size:       [500] kg       │
│                                  │
│ ✓ Target Met: 16.5%             │
│   Progress: [████████░░░░░░░░] │
│                                  │
└──────────────────────────────────┘
```

### 3.2 Ingredient Adjustment UI

**Component: IngredientAdjustmentTable**
```jsx
<IngredientAdjustmentTable
  currentIngredients={[
    {ingredient_id: 1, name: "Maize Germ", percentage: 50, protein: 120},
    {ingredient_id: 2, name: "Wheat Bran", percentage: 30, protein: 80},
    {ingredient_id: 3, name: "Sunflower Cake", percentage: 20, protein: 200}
  ]}
  adjustedIngredients={[
    {ingredient_id: 1, name: "Maize Germ", percentage: 35, adjustment: -15, protein: 120},
    {ingredient_id: 2, name: "Wheat Bran", percentage: 25, adjustment: -5, protein: 80},
    {ingredient_id: 3, name: "Sunflower Cake", percentage: 40, adjustment: +20, protein: 200}
  ]}
  projectedProteinPercent={16.5}
/>
```

**Responsibilities:**
- Show side-by-side comparison: Current → Adjusted percentages
- Display adjustment delta (+/- indicator)
- Show protein_grams_per_kg for each ingredient
- Display visual indicators (↑ for increase, ↓ for decrease)
- Editable percentage fields for fine-tuning

**UI Elements:**
```
┌──────────────────────────────────────────────────────────────────┐
│ Ingredient Adjustments                                           │
├──────────────────────────────────────────────────────────────────┤
│ Ingredient         │ Current │ Adjusted │ Change │ Protein (g/kg)│
├────────────────────┼─────────┼──────────┼────────┼────────────────┤
│ Maize Germ         │   50%   │   35%    │ ↓ 15%  │     120        │
│ Wheat Bran         │   30%   │   25%    │ ↓ 5%   │      80        │
│ Sunflower Cake     │   20%   │   40%    │ ↑ 20%  │     200        │
├────────────────────┴─────────┴──────────┴────────┴────────────────┤
│ Projected Protein: 16.5% ✓                                        │
└──────────────────────────────────────────────────────────────────┘
```

### 3.3 Milk Lab Integration

**When Milk Lab calculates feeding plan:**
1. Extract `herd_total_target_liters` from result
2. Store `yield_target_id` in component state
3. Add "Export to Feed Formulation" button

**Button Handler:**
```javascript
async function exportToFeedFormulation(yieldTargetId) {
  // Call backend to get suggested mix
  const response = await fetch('/api/v1/feed-formulation/suggested-mix?yield_target_id=' + yieldTargetId);
  const data = await response.json();
  
  // Navigate to Nutrition Lab with pre-populated state
  navigate('/nutrition-lab', {
    state: {
      suggestedProteinPercent: data.suggested_protein_percent,
      suggestedIngredients: data.suggested_ingredients,
      herdTargetLiters: data.herd_total_target_liters,
      batchSizeKg: data.batch_size_kg,
      yieldTargetId: yieldTargetId
    }
  });
}
```

### 3.4 Recipe Auto-Save UI

**Component: RecipeSaveDialog**
```jsx
<RecipeSaveDialog
  suggestedName={`Herd Target ${herdLiters}L - ${proteinPercent}% Protein`}
  targetProteinPercent={16.5}
  adjustedIngredients={adjustedIngredients}
  batchSizeKg={500}
  onSave={(recipeName, autoApply) => {
    // Call POST /api/v1/recipes/auto-save
  }}
/>
```

**Responsibilities:**
- Show modal/dialog for saving recipe
- Pre-populate recipe name with suggested format
- Option to "Auto-apply to next batches" (checkbox)
- Show summary of recipe before save
- Handle success/error responses

**UI Elements:**
```
┌───────────────────────────────────────────────┐
│ Save Recipe as Current                        │
├───────────────────────────────────────────────┤
│                                               │
│ Recipe Name:                                  │
│ [Herd Target 4.3L - 16.5% Protein]           │
│                                               │
│ Target Protein: 16.5%                         │
│ Batch Size: 500 kg                            │
│                                               │
│ ☐ Auto-apply to next batches                 │
│                                               │
│ Summary:                                      │
│ • Maize Germ: 35%                            │
│ • Wheat Bran: 25%                            │
│ • Sunflower Cake: 40%                        │
│                                               │
│ [Cancel]  [Save Recipe]                      │
└───────────────────────────────────────────────┘
```

---

## 4. State Management

### Redux/Context Store Structure

```javascript
const NutritionLabState = {
  // Milk Lab integration
  yieldTargetId: null,
  herdTotalTargetLiters: 4.3,
  
  // Recipe formulation
  batchSizeKg: 500,
  baseIngredients: [
    {ingredient_id: 1, name: "Maize Germ", percentage: 50},
    {ingredient_id: 2, name: "Wheat Bran", percentage: 30},
    {ingredient_id: 3, name: "Sunflower Cake", percentage: 20}
  ],
  
  // Protein targeting
  currentProteinPercent: 12.4,
  targetProteinPercent: 16.5,
  adjustmentNeeded: 4.1,
  
  // Suggestions
  adjustedIngredients: [
    {ingredient_id: 1, name: "Maize Germ", percentage: 35, adjustment: -15},
    {ingredient_id: 2, name: "Wheat Bran", percentage: 25, adjustment: -5},
    {ingredient_id: 3, name: "Sunflower Cake", percentage: 40, adjustment: +20}
  ],
  projectedProteinPercent: 16.5,
  adjustmentStrategy: "...",
  
  // Loading
  isFormulating: false,
  isSaving: false,
  error: null,
  success: false
};
```

### Redux Actions

```javascript
// Fetch suggested mix from Milk Lab
dispatch(fetchSuggestedMix(yieldTargetId, batchSizeKg));

// Calculate current nutrition
dispatch(calculateNutrition(batchSizeKg, baseIngredients));

// Formulate recipe with target protein
dispatch(formulateRecipe(batchSizeKg, targetProteinPercent, baseIngredients));

// Save recipe
dispatch(autoSaveRecipe(recipeName, batchSizeKg, targetProteinPercent, adjustedIngredients));
```

---

## 5. Complete User Flow (Step-by-Step)

### Scenario A: User Starting from Milk Lab
```
1. User opens "Milk Lab" page
   ↓
2. Sets yield targets for lactating cows (backend saves to yield_target table)
   ↓
3. System calculates herd feeding plan
   ↓
4. User clicks "Export to Feed Formulation"
   ↓
5. Frontend calls GET /api/v1/feed-formulation/suggested-mix?yield_target_id=X
   ↓
6. Backend returns: herd_total_target_liters=4.3, suggested_protein_percent=16.5
   ↓
7. Frontend navigates to "Nutrition Lab" with pre-populated data
   ↓
8. User sees target protein already set to 16.5%
   ↓
9. Frontend calls POST /api/v1/recipes/formulate with current ingredients
   ↓
10. Backend suggests adjusted percentages
    ↓
11. User reviews suggestions and clicks "Save Recipe"
    ↓
12. Frontend calls POST /api/v1/recipes/auto-save
    ↓
13. Recipe saved with status="ADOPTED"
    ↓
14. Next batch automatically uses this recipe
```

### Scenario B: User Starting from Nutrition Lab (Manual)
```
1. User opens "Nutrition Lab" page
   ↓
2. Enters batch size (500 kg) and target protein (16.5%)
   ↓
3. Selects base ingredients with current percentages
   ↓
4. Clicks "Calculate Adjustments"
   ↓
5. Frontend calls POST /api/v1/recipes/calculate-nutrition
   ↓
6. Shows current protein: 12.4%
   ↓
7. User clicks "Formulate to Target"
   ↓
8. Frontend calls POST /api/v1/recipes/formulate
   ↓
9. Backend suggests: Maize down 15%, Wheat down 5%, Sunflower up 20%
   ↓
10. User reviews and clicks "Save as Current Recipe"
    ↓
11. Frontend opens save dialog
    ↓
12. User clicks "Save Recipe"
    ↓
13. Frontend calls POST /api/v1/recipes/auto-save
    ↓
14. Recipe saved and adopted
```

---

## 6. Error Handling

### Frontend should handle these responses:

```javascript
// 400 Bad Request
{
  "error": "target_protein_percent is required (0-100).",
  "details": "..."
}

// 404 Not Found
{
  "error": "Ingredient 999 not found for this tenant."
}

// 500 Server Error
{
  "error": "Failed to formulate recipe.",
  "details": "..."
}

// No yield targets available
{
  "error": "No active yield targets found for lactating cows in this herd.",
  "message": "Please set up yield targets in Milk Lab first."
}
```

### Frontend validations:
- ✓ batch_size_kg > 0
- ✓ target_protein_percent 0-100
- ✓ At least 1 ingredient
- ✓ Ingredient percentages sum to 100% (or handle normalization)
- ✓ All ingredient_ids must exist in tenant's inventory

---

## 7. Integration Checklist

- [ ] Create ProteinTargetInput component
- [ ] Create IngredientAdjustmentTable component
- [ ] Create RecipeSaveDialog component
- [ ] Add "Export to Feed Formulation" button to Milk Lab
- [ ] Implement state management for recipe formulation
- [ ] Implement Redux actions for all 4 API endpoints
- [ ] Add loading spinners during API calls
- [ ] Add error toast notifications
- [ ] Add success toast notifications
- [ ] Implement real-time protein % update as ingredients change
- [ ] Add visual indicators for protein targets (progress bar, checkmarks)
- [ ] Add "Undo" / "Reset to Current" button
- [ ] Implement percentage normalization logic
- [ ] Add unit tests for API integration
- [ ] Test Milk Lab → Feed Formulation flow
- [ ] Test manual recipe formulation flow
- [ ] Test recipe auto-save and adoption

---

## 8. API Response Examples for Testing

### Test Case 1: Basic Nutrition Calculation
```bash
curl -X POST http://localhost:5000/api/v1/recipes/calculate-nutrition \
  -H "Authorization: Bearer {JWT}" \
  -H "Content-Type: application/json" \
  -d '{
    "batch_size_kg": 500,
    "ingredients": [
      {"ingredient_id": 1, "percentage": 50},
      {"ingredient_id": 2, "percentage": 30},
      {"ingredient_id": 3, "percentage": 20}
    ]
  }'
```

### Test Case 2: Formulation with Target
```bash
curl -X POST http://localhost:5000/api/v1/recipes/formulate \
  -H "Authorization: Bearer {JWT}" \
  -H "Content-Type: application/json" \
  -d '{
    "batch_size_kg": 500,
    "target_protein_percent": 16.5,
    "ingredients": [
      {"ingredient_id": 1, "percentage": 50},
      {"ingredient_id": 2, "percentage": 30},
      {"ingredient_id": 3, "percentage": 20}
    ]
  }'
```

### Test Case 3: Auto-Save Recipe
```bash
curl -X POST http://localhost:5000/api/v1/recipes/auto-save \
  -H "Authorization: Bearer {JWT}" \
  -H "Content-Type: application/json" \
  -d '{
    "recipe_name": "Herd Target 4.3L - 16.5% Protein",
    "batch_size_kg": 500,
    "target_protein_percent": 16.5,
    "adjusted_ingredients": [
      {"ingredient_id": 1, "percentage": 35},
      {"ingredient_id": 2, "percentage": 25},
      {"ingredient_id": 3, "percentage": 40}
    ]
  }'
```

---

## Notes for Frontend Team

1. **Protein is measured in grams per kilogram** - The backend stores protein_grams_per_kg in InventoryItem. When displaying to users, divide by 10 to get percentage: (total_protein_grams / batch_size_kg) / 10 = protein %

2. **Auto-normalization** - If ingredient percentages don't sum to 100%, the backend normalizes them. Frontend should either prevent this or show a warning.

3. **Suggested protein target** - Currently hardcoded to 16.5% (industry standard for dairy meals). In future, this can be calculated from historical recipe performance or user preferences.

4. **Ingredient adjustments** - Use a simple proportional algorithm: increase high-protein ingredients when target is higher, increase low-protein ingredients when target is lower.

5. **Recipe adoption** - When a recipe is saved with status="ADOPTED", the next batch should automatically use these ingredient percentages. This is handled by the backend when creating new batches.

6. **Yield target integration** - The yield_target_id is optional but useful for tracking which Milk Lab targets led to specific recipes.

---

## Backend Services Reference

- `RecipeFormulationService.get_ingredient_nutrition_profile()` - Get protein/energy/fiber of single ingredient
- `RecipeFormulationService.calculate_batch_protein_content()` - Calculate current nutrition of recipe
- `RecipeFormulationService.suggest_ingredient_adjustments()` - Get suggestions to hit target protein
- `RecipeFormulationService.save_recipe_from_formulation()` - Save formulated recipe to DB
- `HerdFeedingPlanService.calculate_from_cow_targets()` - Get herd plan from Milk Lab yield targets

All endpoints are protected by JWT authentication and tenant isolation (tenant_id from JWT claims).
