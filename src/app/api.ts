const API_BASE_URL = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api';

export async function uploadFile(file: File) {
  const formData = new FormData();
  formData.append('file', file);
  
  const response = await fetch(`${API_BASE_URL}/upload`, {
    method: 'POST',
    body: formData,
  });
  
  if (!response.ok) {
    throw new Error('Upload failed');
  }
  
  return response.json();
}

export async function getResult(uploadId: string, endpoint: string) {
  const response = await fetch(`${API_BASE_URL}/results/${uploadId}/${endpoint}`);
  
  if (!response.ok) {
    throw new Error(`Failed to fetch ${endpoint} results`);
  }
  
  return response.json();
}

export async function getStatus(uploadId: string) {
  const response = await fetch(`${API_BASE_URL}/status/${uploadId}`);
  
  if (!response.ok) {
    throw new Error('Failed to fetch status');
  }
  
  return response.json();
}
