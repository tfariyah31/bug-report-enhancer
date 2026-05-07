import os
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from llama_cpp import Llama
import re

# --- Paths ---
MODEL_PATH = os.path.join("llm_model", "mistral", "mistral-7b-instruct-v0.2.Q4_K_M.gguf")
DB_DIR = "db"  # same folder you used when building the index

# --- Load the LLM ---
print("Loading local model...")
llm = Llama(model_path=MODEL_PATH, n_ctx=4096, n_threads=4)

# --- Load embeddings + Chroma DB ---
print("Loading Chroma DB and embedding function...")
embedding_function = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
db = Chroma(persist_directory=DB_DIR, embedding_function=embedding_function)

def clean_text(text: str) -> str:
    """Remove stray newlines / extra spaces so chunks read like paragraphs."""
    txt = re.sub(r'\s+', ' ', text)         # collapse all whitespace
    return txt.strip()

print("\n RAG chat is ready! Ask about your PDF (type 'exit' to quit).\n")

while True:
    question = input("You: ").strip()
    if question.lower() in {"exit", "quit"}:
        break

    # 1️⃣ Retrieve top-k chunks
    docs = db.similarity_search(question, k=3)

    print("\n Retrieved passages:")
    for i, d in enumerate(docs, 1):
        source = d.metadata.get("source", "unknown")
        page = d.metadata.get("page", "N/A")
        snippet = clean_text(d.page_content)
        print(f"\n[{i}] {source} (page {page})")
        print(f"***{snippet}***")

    # 2️⃣ Build prompt for the LLM
    context = "\n\n".join(clean_text(d.page_content) for d in docs)
    prompt = (
        "You are a helpful assistant that answers based only on the provided context.\n"
        "If the answer is not in the context, say you don't know.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}\nAnswer:"
    )

    # 3️⃣ Ask the local model
    output = llm.create_chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=512,
        temperature=0.3,
    )
    answer = output["choices"][0]["message"]["content"]
    print("\n🤖 Assistant:", answer, "\n")



