
import asyncio
from services.resume_service import screen_resumes_batch

async def test_resume():
    jd = "Software Engineer with 5+ years experience in Python, React, and SQL. Must have experience with Cloud (AWS/GCP)."
    resume_content = """
    Sneha Iyer
    Experience: 12 years in Software Engineering.
    Skills: Python, Java, React, SQL, Project Planning, Technical Documentation.
    Education: B.E. ECE - NIT.
    """
    
    files = [("Sneha_Iyer_Resume.txt", resume_content.encode('utf-8'))]
    
    print("Testing Resume Screening with Ollama...")
    results = await screen_resumes_batch(files, jd)
    
    for r in results:
        print(f"\nCandidate: {r['name']}")
        print(f"Score: {r['matchScore']}%")
        print(f"Experience: {r['experience']}")
        print(f"Education: {r['education']}")
        print(f"Matched Skills: {r['matchedSkills']}")
        print(f"Missing Skills: {r['missingSkills']}")
        print(f"Strengths: {r['strengths']}")
        print(f"Weaknesses: {r['weaknesses']}")
        print(f"Pipeline: {r['modelPipeline']['embeddings']}")

if __name__ == "__main__":
    asyncio.run(test_resume())
