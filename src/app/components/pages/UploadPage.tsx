import { useState, useRef } from "react";
import { useNavigate } from "react-router";
import { Upload, FileText, Loader2 } from "lucide-react";
import { Button } from "../ui/button";
import { uploadFile } from "../../api";
import { useAppContext } from "../../context/AppContext";

export function UploadPage() {
  const navigate = useNavigate();
  const { setUploadId, isLoading, setIsLoading } = useAppContext();
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileUpload = async (file: File) => {
    try {
      setIsLoading(true);
      const data = await uploadFile(file);
      setUploadId(data.upload_id);
      navigate("/overview");
    } catch (error) {
      console.error("Upload failed:", error);
      alert("Failed to upload file. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFileUpload(file);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFileUpload(file);
  };

  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="w-full max-w-3xl">
        {/* Header */}
        <div className="text-center mb-12">
          <h2 className="text-3xl font-sans mb-3 text-foreground">
            Upload Transaction Data
          </h2>
          <p className="text-muted-foreground">
            Import your CSV file to analyze spending patterns, detect anomalies, and generate predictions
          </p>
        </div>

        {/* Drag and Drop Zone */}
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`
            border-2 border-dashed rounded-lg p-12 mb-8 transition-all duration-200
            ${isDragging 
              ? "border-primary bg-primary/10" 
              : "border-border hover:border-primary/50"}
          `}
        >
          <div className="flex flex-col items-center">
            <div className="w-16 h-16 rounded-full bg-secondary flex items-center justify-center mb-4">
              <Upload className="w-8 h-8 text-primary" />
            </div>
            <h3 className="text-lg font-sans mb-2 text-foreground">
              Drop your CSV file here
            </h3>
            <p className="text-sm text-muted-foreground mb-4">
              or click to browse
            </p>
            <input
              type="file"
              accept=".csv"
              className="hidden"
              id="file-upload"
              ref={fileInputRef}
              onChange={handleFileChange}
              disabled={isLoading}
            />
            <label htmlFor="file-upload">
              <Button 
                variant="outline" 
                className="cursor-pointer border-primary/50 hover:bg-primary/10 hover:border-primary"
                asChild
                disabled={isLoading}
              >
                <span>
                  {isLoading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <FileText className="w-4 h-4 mr-2" />}
                  {isLoading ? "Uploading..." : "Select File"}
                </span>
              </Button>
            </label>
          </div>
        </div>

        {/* Expected CSV Schema */}
        <div className="bg-card border border-border rounded-lg p-6">
          <h4 className="text-sm font-mono uppercase tracking-wider text-muted-foreground mb-4">
            Expected CSV Schema
          </h4>
          
          <div className="overflow-hidden rounded-lg border border-border">
            <table className="w-full">
              <thead className="bg-secondary">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-mono uppercase tracking-wider text-muted-foreground">
                    Column
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-mono uppercase tracking-wider text-muted-foreground">
                    Type
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-mono uppercase tracking-wider text-muted-foreground">
                    Required
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-mono uppercase tracking-wider text-muted-foreground">
                    Example
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                <tr className="hover:bg-secondary/30 transition-colors">
                  <td className="px-4 py-3 font-mono text-sm text-foreground">date</td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">Date</td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-primary/20 text-primary">
                      Yes
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-sm text-muted-foreground">2024-03-15</td>
                </tr>
                <tr className="hover:bg-secondary/30 transition-colors">
                  <td className="px-4 py-3 font-mono text-sm text-foreground">amount</td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">Number</td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-primary/20 text-primary">
                      Yes
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-sm text-muted-foreground">$52.40</td>
                </tr>
                <tr className="hover:bg-secondary/30 transition-colors">
                  <td className="px-4 py-3 font-mono text-sm text-foreground">category</td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">String</td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-muted/50 text-muted-foreground">
                      Optional
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-sm text-muted-foreground">Groceries</td>
                </tr>
                <tr className="hover:bg-secondary/30 transition-colors">
                  <td className="px-4 py-3 font-mono text-sm text-foreground">description</td>
                  <td className="px-4 py-3 text-sm text-muted-foreground">String</td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-mono bg-muted/50 text-muted-foreground">
                      Optional
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-sm text-muted-foreground">Whole Foods</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Sample Data Preview */}
          <div className="mt-6 pt-6 border-t border-border">
            <p className="text-xs text-muted-foreground mb-3 font-mono uppercase tracking-wider">
              Sample Data
            </p>
            <div className="bg-background rounded border border-border p-3 font-mono text-xs overflow-x-auto">
              <pre className="text-muted-foreground">
{`date,amount,category,description
2024-03-15,52.40,Groceries,Whole Foods
2024-03-14,120.00,Utilities,Electric Bill
2024-03-13,18.50,Food,Coffee Shop`}
              </pre>
            </div>
          </div>
        </div>

        {/* Action Button */}
        <div className="mt-8 text-center">
          <Button
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading}
            className="bg-primary hover:bg-primary/90 text-primary-foreground px-8 py-6 text-base"
          >
            {isLoading ? (
              <Loader2 className="w-5 h-5 mr-2 animate-spin" />
            ) : (
              <FileText className="w-5 h-5 mr-2" />
            )}
            {isLoading ? "Processing..." : "Analyze Transactions"}
          </Button>
        </div>
      </div>
    </div>
  );
}
