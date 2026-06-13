export const DEFAULT_LIBRARY = {
  categories: [
    { id: "all", name: "All Notes", parentId: null, order: 0, system: true },
    { id: "uncategorized", name: "Uncategorized", parentId: null, order: 1, system: true },
  ],
  notes: [],
};

export const DEFAULT_READER_MESSAGE = {
  role: "assistant",
  content: "Paper Notes agent is ready.",
};
