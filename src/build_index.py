from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
import os
import json

# --- Paths ---
DATA_DIR = "data"
DB_DIR = "db"

SUPPORTED_EXTENSIONS = [".pdf", ".md", ".txt", ".json"]

def load_all_documents(data_dir: str):
    """Load all supported files from the data folder."""
    all_docs = []

    for filename in sorted(os.listdir(data_dir)):
        filepath = os.path.join(data_dir, filename)
        ext = os.path.splitext(filename)[1].lower()

        if ext not in SUPPORTED_EXTENSIONS:
            print(f"  Skipping: {filename}")
            continue

        print(f"  Loading: {filename}")

        try:
            if ext == ".pdf":
                loader = PyPDFLoader(filepath)
                docs = loader.load()

            elif ext in (".md", ".txt"):
                loader = TextLoader(filepath, encoding="utf-8")
                docs = loader.load()

            elif ext == ".json":
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                json_text = json.dumps(data, indent=2)
                docs = [Document(page_content=json_text, metadata={"source": filepath})]

            # Tag each doc with its source filename
            for doc in docs:
                doc.metadata["source"] = filepath
                doc.metadata["filename"] = filename

            all_docs.extend(docs)
            print(f"    → {len(docs)} section(s) loaded")

        except Exception as e:
            print(f"  ⚠️  Failed to load {filename}: {e}")

    return all_docs


# --- Load all documents ---
print("Loading documents from data/...")
documents = load_all_documents(DATA_DIR)
print(f"\nTotal documents loaded: {len(documents)}")

if not documents:
    print("❌ No documents found in data/. Add your files and try again.")
    exit(1)

# --- Split into chunks ---
print("\nSplitting into chunks...")
splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
chunks = splitter.split_documents(documents)
print(f"Total chunks: {len(chunks)}")

# --- Create embeddings ---
print("\nLoading embedding model...")
embedding_function = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

# --- Store in Chroma (auto-persists in newer versions) ---
print(f"\nSaving {len(chunks)} chunks to Chroma DB at '{DB_DIR}'...")
Chroma.from_documents(
    documents=chunks,
    embedding=embedding_function,
    persist_directory=DB_DIR,
)

print("\n✅ Done! Vector database stored in:", DB_DIR)
print("\nFiles indexed:")
indexed = set()
for chunk in chunks:
    indexed.add(chunk.metadata.get("filename", "unknown"))
for f in sorted(indexed):
    print(f"  - {f}")