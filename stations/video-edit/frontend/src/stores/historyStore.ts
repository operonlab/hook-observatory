import { create } from "zustand";
import { devtools } from "zustand/middleware";

export interface Command {
  readonly type: string;
  readonly description: string;
  execute(): Promise<void>;
  undo(): Promise<void>;
}

const MAX_HISTORY = 100;

interface HistoryState {
  undoStack: Command[];
  redoStack: Command[];
  canUndo: boolean;
  canRedo: boolean;
}

interface HistoryActions {
  execute: (command: Command) => Promise<void>;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
  clear: () => void;
}

export const useHistoryStore = create<HistoryState & HistoryActions>()(
  devtools(
    (set, get) => ({
      undoStack: [],
      redoStack: [],
      canUndo: false,
      canRedo: false,

      execute: async (command) => {
        await command.execute();
        set((s) => {
          const undoStack = [...s.undoStack, command];
          if (undoStack.length > MAX_HISTORY) undoStack.shift();
          return {
            undoStack,
            redoStack: [],
            canUndo: true,
            canRedo: false,
          };
        });
      },

      undo: async () => {
        const { undoStack } = get();
        if (undoStack.length === 0) return;
        const command = undoStack[undoStack.length - 1];
        await command.undo();
        set((s) => {
          const newUndo = s.undoStack.slice(0, -1);
          return {
            undoStack: newUndo,
            redoStack: [...s.redoStack, command],
            canUndo: newUndo.length > 0,
            canRedo: true,
          };
        });
      },

      redo: async () => {
        const { redoStack } = get();
        if (redoStack.length === 0) return;
        const command = redoStack[redoStack.length - 1];
        await command.execute();
        set((s) => {
          const newRedo = s.redoStack.slice(0, -1);
          return {
            undoStack: [...s.undoStack, command],
            redoStack: newRedo,
            canUndo: true,
            canRedo: newRedo.length > 0,
          };
        });
      },

      clear: () =>
        set({ undoStack: [], redoStack: [], canUndo: false, canRedo: false }),
    }),
    { name: "historyStore" },
  ),
);
